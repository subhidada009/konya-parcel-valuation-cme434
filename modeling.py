"""Spatial model tuning, holdout evaluation and TreeSHAP."""
import os

# Cap native parallelism for a shared, CPU-only deployment.
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from scipy.spatial import cKDTree
from sklearn.base import clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

from spatial import FEATURES, NUMERIC, block_key

SEED = 434
CANDIDATES = {
    'Random Forest': [dict(n_estimators=120,max_depth=depth,min_samples_leaf=leaf,max_features=frac)
                      for depth,leaf,frac in [(8,2,0.8),(14,3,0.8),(None,1,1.0),(None,5,0.65)]],
    'XGBoost': [dict(n_estimators=n,max_depth=depth,learning_rate=rate,subsample=.9,colsample_bytree=.9)
                for n,depth,rate in [(110,2,.05),(140,3,.04),(120,4,.045),(180,3,.028)]],
    'LightGBM': [dict(n_estimators=n,num_leaves=leaves,learning_rate=rate,min_child_samples=child)
                 for n,leaves,rate,child in [(110,7,.05,12),(135,11,.04,12),(145,15,.035,16),(170,7,.03,20)]],
}


def make_model(family, configuration):
    if family == 'Random Forest':
        estimator = RandomForestRegressor(**configuration['params'],random_state=SEED,n_jobs=1)
    elif family == 'XGBoost':
        estimator = XGBRegressor(**configuration['params'],random_state=SEED,n_jobs=1,
                                 tree_method='hist',objective='reg:squarederror')
    else:
        estimator = LGBMRegressor(**configuration['params'],random_state=SEED,n_jobs=1,verbosity=-1,
                                  deterministic=True,force_col_wise=True)
    prep = ColumnTransformer([
        ('numerical',SimpleImputer(strategy='median',keep_empty_features=True),list(NUMERIC)),
        ('zoning',OneHotEncoder(sparse_output=False,handle_unknown='ignore'),['imar_durumu'])],
        verbose_feature_names_out=False).set_output(transform='pandas')
    target = TransformedTargetRegressor(regressor=estimator, func=np.log1p, inverse_func=np.expm1) if configuration['log_target'] else estimator
    return Pipeline([('features',prep),('model',target)])


def predict(model, frame):
    return np.maximum(0,model.predict(frame.loc[:,list(FEATURES)]))


def score(target, estimates):
    return {'r2':float(r2_score(target,estimates)), 'rmse':float(root_mean_squared_error(target,estimates)),
            'mae':float(mean_absolute_error(target,estimates)),
            'median_signed_error':float(np.median(np.asarray(estimates)-np.asarray(target)))}


def train_model(family, configuration, frame):
    return make_model(family,configuration).fit(frame.loc[:,list(FEATURES)],frame.unit_tl_m2)


def tune(family, frame, splits=4):
    groups = block_key(frame)
    folds = list(GroupKFold(n_splits=min(splits,len(set(groups)))).split(frame,groups=groups))
    scores = []
    for params in CANDIDATES[family]:
        for log_target in (False,True):
            config = {'params':params,'log_target':log_target}
            errors = np.empty(len(frame),dtype=float)
            for train, test in folds:
                model = train_model(family,config,frame.iloc[train])
                errors[test] = predict(model,frame.iloc[test])
            scores.append({**config,**score(frame.unit_tl_m2,errors)})
    order = sorted(scores,key=lambda d:d['rmse'])
    return {k:order[0][k] for k in ('params','log_target')},scores


def compare(frame):
    groups = block_key(frame)
    outer = list(GroupKFold(n_splits=5).split(frame, groups=groups))
    metrics = {}
    predictions = pd.DataFrame({'parcel_id':frame.parcel_id,'block':groups,
                                'observed_tl_m2':frame.unit_tl_m2})
    folds = []
    for index,(train,test) in enumerate(outer,1):
        assert set(groups[train]).isdisjoint(groups[test])
        predictions.loc[test,'fold'] = index
        folds.append({'fold':index,'test_n':len(test),'train_n':len(train),'test_blocks':sorted(set(groups[test]))})
    baseline = np.empty(len(frame))
    for train,test in outer:
        baseline[test] = frame.iloc[train].unit_tl_m2.mean()
    predictions['Train mean baseline'] = baseline
    for family in CANDIDATES:
        estimates = np.empty(len(frame))
        fold_results = []
        tuning = []
        for index,(train,test) in enumerate(outer,1):
            configuration, trials = tune(family,frame.iloc[train].reset_index(drop=True))
            trained = train_model(family,configuration,frame.iloc[train])
            estimates[test] = predict(trained,frame.iloc[test])
            fold_results.append({'fold':index,**score(frame.iloc[test].unit_tl_m2,estimates[test]),
                                 'selected':configuration})
            tuning.append({'outer_fold':index,'trials':trials})
        config, final_trials = tune(family,frame,5)
        predictions[family] = estimates
        metrics[family] = {'metrics':score(frame.unit_tl_m2,estimates),'folds':fold_results,
                           'outer_tuning':tuning,'full_tuning':final_trials,'selected':config}
        print(family,metrics[family]['metrics'],config,flush=True)
    best = min(metrics,key=lambda key:metrics[key]['metrics']['rmse'])
    first_train, first_test = outer[0]
    audit_config = metrics[best]['folds'][0]['selected']
    audit_model = train_model(best,audit_config,frame.iloc[first_train])
    production = train_model(best,metrics[best]['selected'],frame)
    results = {'models':metrics,'best_model':best, 'folds':folds,'observations':len(frame),
               'block_size_m':20_000, 'occupied_blocks':len(set(groups)),
               'baseline':score(frame.unit_tl_m2,baseline),
               'update_holdout':{'blocks':folds[0]['test_blocks'],'test_n':len(first_test),
                                 'config':audit_config,**score(frame.iloc[first_test].unit_tl_m2,
                                                             predict(audit_model,frame.iloc[first_test]))}}
    return production, results, predictions


def explain(model, frame, family):
    features = model.named_steps['features'].transform(frame.loc[:,list(FEATURES)])
    estimator = model.named_steps['model']
    log = isinstance(estimator,TransformedTargetRegressor)
    if log:
        estimator = estimator.regressor_
    if family == 'XGBoost':
        import xgboost as xgb
        contributions = estimator.get_booster().predict(xgb.DMatrix(features),pred_contribs=True)
        expected, values = contributions[:,-1], contributions[:,:-1]
    elif family == 'LightGBM':
        contributions = estimator.predict(features,pred_contrib=True)
        expected, values = contributions[:,-1], contributions[:,:-1]
    else:
        import shap
        explainer = shap.TreeExplainer(estimator)
        values = explainer.shap_values(features)
        expected = np.full(len(frame),float(np.asarray(explainer.expected_value).item()))
    reconstructed = expected + np.sum(values,axis=1)
    max_error = float(np.max(abs(reconstructed - estimator.predict(features))))
    keys = list(NUMERIC) + ['imar_durumu']
    grouped = np.column_stack([values[:,:len(NUMERIC)], values[:,len(NUMERIC):].sum(axis=1)])
    summary = pd.DataFrame({'feature':keys,'mean_abs_shap':np.abs(grouped).mean(axis=0),
                            'mean_signed_shap':grouped.mean(axis=0)}).sort_values('mean_abs_shap',ascending=False)
    detail = pd.DataFrame(grouped,columns=keys).assign(parcel_id=frame.parcel_id,base=expected)
    return summary, detail, {'scale':'log1p(TL/m²)' if log else 'TL/m²','max_additivity_error':max_error}


def moran_statistics(frame, columns, k=8, permutations=999):
    n = len(frame)
    points = frame[['x','y']].to_numpy()
    _, nearest = cKDTree(points).query(points,k=k+1)
    neighbors = np.zeros((n,n),dtype=bool)
    for i, candidates in enumerate(nearest):
        neighbors[i,[int(v) for v in candidates if v != i][:k]] = True
    symmetric = neighbors | neighbors.T
    weights = symmetric / symmetric.sum(axis=1,keepdims=True)
    rng = np.random.default_rng(SEED)
    rows = pd.DataFrame(index=frame.index)
    results = {}
    for key, values in columns.items():
        z = (values-np.mean(values))/np.std(values)
        lag = weights @ z
        observed = z @ lag / (z @ z)
        expected = -1/(n-1)
        randomized = np.stack([rng.permutation(z) for _ in range(permutations)])
        null = np.einsum('ij,ij->i', randomized @ weights, randomized)/(z@z)
        p = (1 + np.count_nonzero(abs(null-expected) >= abs(observed-expected))) / (permutations+1)
        results[key] = {'i':float(observed),'expected_i':expected,'p_two_sided':float(p),
                        'k':k,'permutations':permutations,'weights':'symmetric kNN, row standardized'}
        if key != 'unit_tl_m2':
            continue
        local = z*lag
        p_local = np.empty(n)
        for i, degree in enumerate(symmetric.sum(axis=1)):
            rest = np.delete(z,i)
            samples = np.stack([rng.choice(rest,size=degree,replace=False) for _ in range(permutations)])
            values = z[i]*samples.mean(axis=1)
            expectation = -z[i]**2/(n-1)
            p_local[i] = (1+np.count_nonzero(abs(values-expectation) >= abs(local[i]-expectation)))/(permutations+1)
        sort = np.argsort(p_local)
        adjusted = np.empty(n)
        adjusted[sort] = np.minimum.accumulate((p_local[sort]*n/np.arange(1,n+1))[::-1])[::-1].clip(0,1)
        quadrant = np.where(z>=0,np.where(lag>=0,'High–High','High–Low'),np.where(lag>=0,'Low–High','Low–Low'))
        rows['local_moran_i'],rows['p_local'],rows['q_bh'] = local,p_local,adjusted
        rows['quadrant'] = quadrant
        rows['lisa_fdr_05'] = np.where(adjusted<=.05,quadrant,'Not significant')
        rows['lisa_nominal_05'] = np.where(p_local<=.05,quadrant,'Not significant')
        results[key]['local_fdr_counts'] = rows.lisa_fdr_05.value_counts().to_dict()
        results[key]['local_nominal_counts'] = rows.lisa_nominal_05.value_counts().to_dict()
    return results,rows
