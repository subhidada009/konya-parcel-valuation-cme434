"""Build the publication-ready figures from the released analysis outputs."""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
import rasterio as rio
from rasterio.plot import plotting_extent
from shapely.geometry import shape

from spatial import ROOT, projected

OUT=ROOT/'artifacts'
FIG=OUT/'figures'
GEO=ROOT/'data'/'geo'
INK='#17382f'
MUTED='#536c63'
PALE='#edf2e9'
PALETTE=['#1f4e65','#357b85','#71a594','#e4b96a','#b85c40']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'text.color':INK,'axes.labelcolor':INK,
                    'xtick.color':MUTED,'ytick.color':MUTED,'axes.titlesize':13,'axes.titleweight':'bold',
                    'axes.spines.top':False,'axes.spines.right':False})


def boundary_line(ax,boundary,color=INK,lw=.85):
    for geom in getattr(boundary,'geoms',[boundary]):
        ax.plot(*geom.exterior.xy,color=color,lw=lw,zorder=4)


def map_frame(ax,boundary):
    x0,y0,x1,y1=boundary.bounds
    ax.set(xlim=(x0-11000,x1+11000),ylim=(y0-11000,y1+11000),aspect='equal')
    ax.set_facecolor(PALE)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)
    ax.annotate('N',(.933,.92),xycoords='axes fraction',ha='center',va='bottom',weight='bold')
    ax.annotate('',(.933,.92),(.933,.85),xycoords='axes fraction',arrowprops={'arrowstyle':'-|>','color':INK,'lw':1})
    left=x0+5000; bottom=y0+5500
    ax.plot([left,left+50000],[bottom,bottom],color=INK,lw=2)
    ax.text(left,bottom+3200,'50 km',fontsize=7)


def save(fig,name):
    fig.savefig(FIG/name,dpi=220,bbox_inches='tight',pad_inches=.15,facecolor='white')
    plt.close(fig)


def main():
    FIG.mkdir(exist_ok=True)
    boundary=projected(shape(json.loads((GEO/'konya.geojson').read_text())['geometry']))
    lisa=pd.read_csv(OUT/'lisa_points.csv')
    with rio.open(GEO/'sentinel_rgb_200m.tif') as file:
        raw=file.read().transpose(1,2,0)
        alpha=np.any(raw>0,axis=2)*255
        rgb=np.dstack([raw,alpha]).astype('uint8')
        ext=plotting_extent(file)
    meta=json.loads((GEO/'raster_provenance.json').read_text())
    dates=sorted({s['datetime'][:10] for s in meta['sentinel_scenes'] if s['used_cells_in_study_area']})
    fig,ax=plt.subplots(figsize=(8.6,5.3))
    map_frame(ax,boundary)
    ax.imshow(rgb,extent=ext,interpolation='nearest')
    boundary_line(ax,boundary,'#fbda8d',1.4)
    ax.scatter(lisa.x,lisa.y,facecolors='white',edgecolors='#234d40',lw=.5,s=11,zorder=5)
    ax.set_title('Konya Province | Sentinel-2 natural-colour mosaic',loc='left',pad=10)
    ax.text(.012,.985,f'{dates[0]} to {dates[-1]} UTC  •  300 modelled listing pins',transform=ax.transAxes,
            fontsize=8.4,va='top',bbox={'facecolor':'white','edgecolor':'none','alpha':.94,'pad':5},zorder=10)
    save(fig,'01_konya_sentinel_rgb.png')

    classes={'Not significant':'#a2b5ab','High–High':'#b94440','Low–Low':'#2b6489','High–Low':'#ed9c63','Low–High':'#416e95'}
    fig,axes=plt.subplots(1,2,figsize=(9.5,4.6),layout='constrained')
    for ax,col,title in zip(axes,['lisa_fdr_05','lisa_nominal_05'],['FDR-adjusted q ≤ 0.05','Exploratory nominal p ≤ 0.05']):
        map_frame(ax,boundary); boundary_line(ax,boundary)
        for name,color in classes.items():
            vals=lisa.loc[lisa[col].eq(name)]
            ax.scatter(vals.x,vals.y,s=10 if name=='Not significant' else 25,c=color,edgecolors='white',linewidths=.25,zorder=3)
        ax.set_title(title,loc='left')
    fig.suptitle('Local spatial association of advertised unit prices',x=.03,ha='left',weight='bold',fontsize=15)
    axes[0].legend(handles=[Line2D([0],[0],marker='o',ls='',color=color,label=name,markersize=5)
                             for name,color in classes.items()],loc='upper left',frameon=True,fontsize=7)
    save(fig,'02_konya_lisa.png')

    with rio.open(OUT/'valuation_grid_1km.tif') as file:
        values=file.read(1); index=file.read(2); ext=plotting_extent(file)
    med=float(np.nanmedian(values))
    fig,axes=plt.subplots(1,2,figsize=(9.6,4.8),layout='constrained')
    for ax,img,cut,title,unit in [(axes[0],values,np.array([0,.5,.8,1.2,1.8,400])*med,'Predicted asking price','TL/m²'),
                                  (axes[1],index,[0,50,80,120,180,40000],'Land price index','Index')]:
        map_frame(ax,boundary); boundary_line(ax,boundary)
        ax.imshow(img,extent=ext,cmap=ListedColormap(PALETTE),norm=BoundaryNorm(cut,5,clip=True),interpolation='nearest')
        ax.set_title(title,loc='left')
        limits=[f'{x:,.0f}' for x in cut[1:-1]]
        labels=[f'<{limits[0]}',f'{limits[0]}–<{limits[1]}',f'{limits[1]}–<{limits[2]}',
                f'{limits[2]}–<{limits[3]}',f'≥{limits[3]}']
        ax.legend(handles=[Patch(facecolor=c,label=l) for c,l in zip(PALETTE,labels)],title=unit,
                  loc='upper left',frameon=True,fontsize=7,title_fontsize=7)
    fig.suptitle('1 km valuation grid | Tarla · 5,305.5 m²',x=.035,ha='left',weight='bold',fontsize=15)
    save(fig,'03_konya_valuation_grid.png')

    shap=pd.read_csv(OUT/'shap_summary.csv').head(10).sort_values('mean_abs_shap')
    names={'dist_transit_m':'Distance to public transport','imar_durumu':'Zoning (grouped)',
           'dist_city_centre_m':'Distance to Konya centre','dist_park_m':'Distance to park',
           'area_m2':'Parcel area','dist_hospital_m':'Distance to hospital','dist_main_road_m':'Distance to main road',
           'dist_school_m':'Distance to school','elevation_600m':'Mean elevation','ndvi_600m':'Mean NDVI',
           'ndvi_sd_600m':'NDVI local variation','elevation_sd_600m':'Elevation local variation',
           'ndbi_600m':'Mean NDBI','mndwi_600m':'Mean MNDWI','dist_waterway_m':'Distance to river or canal',
           'slope_600m':'Mean slope','transit_count_1km':'Transit features within 1 km'}
    fig,ax=plt.subplots(figsize=(8.4,4.4),layout='constrained')
    ax.barh(shap.feature.map(names),shap.mean_abs_shap,color=['#5e9887']*7+['#245d4b']*3,height=.66)
    ax.set(xlabel='Mean absolute TreeSHAP contribution · log(1 + TL/m²)',xlim=(0,.57))
    ax.set_title('LightGBM | Most influential predictors',loc='left',pad=9)
    ax.xaxis.grid(alpha=.2); ax.set_axisbelow(True); ax.spines['left'].set_visible(False); ax.tick_params(axis='y',length=0)
    for i,v in enumerate(shap.mean_abs_shap): ax.text(v+.008,i,f'{v:.3f}',va='center',fontsize=8)
    save(fig,'04_konya_shap.png')

    oof=pd.read_csv(OUT/'spatial_cv_predictions.csv')
    fig,axes=plt.subplots(1,2,figsize=(9,4.25),layout='constrained')
    ax=axes[0]; map_frame(ax,boundary); boundary_line(ax,boundary)
    folds=['#b55a4b','#2e6c88','#8e6cad','#427d50','#b07f2d']
    for fold,color in enumerate(folds,1):
        matched=lisa.loc[lisa.fold.eq(fold)]
        ax.scatter(matched.x,matched.y,s=19,c=color,edgecolors='white',lw=.25,label=f'Fold {fold}')
    ax.set_title('Held-out spatial folds',loc='left'); ax.legend(loc='upper left',fontsize=7)
    x=oof.observed_tl_m2; y=oof.LightGBM
    ax=axes[1]
    ax.scatter(np.log10(x+1),np.log10(y+1),s=17,color='#397666',alpha=.63,edgecolors='none')
    end=max(np.log10(x+1).max(),np.log10(y+1).max())
    ax.plot([0,end],[0,end],ls='--',c='#a86e45',lw=1)
    ax.set(xlabel='Observed asking price · log₁₀(1 + TL/m²)',ylabel='Predicted · log₁₀(1 + TL/m²)',xlim=(0,end+.16),ylim=(0,end+.16))
    ax.set_title('LightGBM out-of-fold predictions',loc='left'); ax.grid(alpha=.2)
    save(fig,'05_konya_spatial_validation.png')


if __name__=='__main__':
    main()
