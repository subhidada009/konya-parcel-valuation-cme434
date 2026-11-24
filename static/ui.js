"use strict";

const el = id => document.getElementById(id);
const fmt = (value, digits = 0) => Number(value).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const signed = (value, digits = 1) => `${value > 0 ? "+" : ""}${fmt(value, digits)}`;
const state = { version: sessionStorage.getItem("konya-version") || "v1.0.0", view:"explore",
  scenario:null, picking:false, overlay:null, pin:null, scenarioPin:null, listing:null, estimate:null, requestId:0 };
const stops = { Underpriced:"#236f54", Fair:"#455d80", Overpriced:"#a65342" };
let map, metadata, markers, boundary;

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "The server could not complete this request.");
  return body;
}

function error(message = "") {
  el("global-error").textContent = message;
  el("global-error").hidden = !message;
}

function selectView(view) {
  state.view = view;
  document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed",button.dataset.view === view));
  document.querySelectorAll(".view").forEach(panel => { panel.hidden = panel.id !== view; });
  if (view !== "scenarios") {
    state.picking = false;
    el("scenario-pick").textContent = "Pick on map";
  }
}

function option(select, value, label = value) {
  const item = element("option",label);
  item.value = value;
  select.append(item);
}

function parameters(extra = {}) {
  const params = new URLSearchParams({version: state.version});
  if (state.scenario) {
    params.set("scenario",state.scenario.type);
    params.set("scenario_latitude",state.scenario.lat);
    params.set("scenario_longitude",state.scenario.lon);
  }
  for (const [key,value] of Object.entries(extra)) {
    if (value !== "" && value !== null && value !== undefined) params.set(key,value);
  }
  return params;
}

function gridParams() {
  return parameters({zoning:el("zoning").value,mode:el("surface").value,value_class:el("value-class").value});
}

function listingParams() {
  return parameters({filter_zoning:el("filter-zoning").value,budget:el("budget").value,
    min_area:el("min-area").value,max_area:el("max-area").value,listing_class:el("listing-class").value});
}

function legend(data) {
  const mode = el("surface").value;
  const title = mode === "index" ? "Price index · study-area median = 100" :
    mode === "delta" ? "Scenario change · TL/m²" : "Estimated TL/m²";
  const edges = data.breaks.map(value => fmt(value,mode === "price" && value < 100 ? 1 : 0));
  const labels = [`< ${edges[0]}`,`${edges[0]} – <${edges[1]}`,`${edges[1]} – <${edges[2]}`,
    `${edges[2]} – <${edges[3]}`,`≥ ${edges[3]}`];
  const row = element("div",undefined,"legend-row");
  labels.forEach((label,i) => {
    const chip = element("span",undefined,"chip");
    const color = element("i",undefined,"swatch");
    color.style.background = data.palette[i];
    chip.append(color,element("span",label));
    row.append(chip);
  });
  el("legend").replaceChildren(element("div",title,"legend-title"),row);
}

function listingCard(item) {
  const button = element("button",undefined,"listing");
  button.type = "button";
  button.append(element("strong",`${item.parcel_id} · ${item.imar_durumu}`),element("span",`${fmt(item.price_tl)} TL`),
    element("small",`${fmt(item.area_m2)} m² · ${fmt(item.unit_tl_m2)} TL/m²`),
    element("span",`${signed(item.asking_gap_pct)}%`, `gap ${item.asking_gap_pct < -15 ? "good" : item.asking_gap_pct > 15 ? "bad" : ""}`));
  button.addEventListener("click",()=>selectListing(item,true));
  return button;
}

function plotListings(data) {
  markers.clearLayers();
  el("listing-count").textContent = `${data.count} found`;
  const cards = data.listings.slice(0,20).map(listingCard);
  if (!cards.length) cards.push(element("p","No listings match those filters.","hint"));
  el("listing-results").replaceChildren(...cards);
  data.listings.forEach(item => {
    const marker = L.circleMarker([item.latitude,item.longitude],{radius:4.5,weight:1.1,color:"#fff",
      fillColor:stops[item.assessment],fillOpacity:.95,bubblingMouseEvents:false});
    marker.on("click",()=>selectListing(item,false));
    markers.addLayer(marker);
  });
}

async function refresh() {
  const id = ++state.requestId;
  error();
  const grid = gridParams();
  const listing = listingParams();
  try {
    const surface = await api(`/api/grid?${grid}`);
    if (id !== state.requestId) return;
    el("map-subtitle").textContent = `${fmt(surface.cells)} cells · ${el("zoning").value} · ${fmt(surface.reference_area_m2,1)} m² reference parcel`;
    const updated = L.imageOverlay(`/api/grid?${grid}&format=png`,metadata.map_bounds,{opacity:.91,interactive:false,pane:"surface"});
    updated.once("load",()=> {
      if (id !== state.requestId) { updated.remove(); return; }
      if (state.overlay) state.overlay.remove();
      state.overlay = updated;
    });
    updated.once("error",()=>{updated.remove();error("The valuation surface could not be drawn.");});
    updated.addTo(map);
    legend(surface);
    el("grid-download").href = `/api/grid?${grid}&format=csv`;
    el("listing-download").href = `/api/listings?${listing}&download=csv`;
    if (state.scenario) {
      const div = element("div",`${fmt(surface.scenario_changed_cells)} grid cells change for ${el("zoning").value}.`);
      div.append(element("div",`Range ${signed(surface.delta_min,2)} to ${signed(surface.delta_max,2)} TL/m².`));
      el("scenario-output").replaceChildren(div);
    }
    const records = await api(`/api/listings?${listing}`);
    if (id === state.requestId) plotListings(records);
  } catch (e) { if (id === state.requestId) error(e.message); }
}

function setPin(lat,lon) {
  if (state.pin) state.pin.remove();
  state.pin = L.circleMarker([lat,lon],{radius:8,color:"#fff",weight:2.6,fillColor:"#153c35",fillOpacity:1}).addTo(map);
}

function selectListing(item, zoom) {
  state.listing = item;
  el("lat").value = item.latitude;
  el("lon").value = item.longitude;
  el("asking").value = item.price_tl;
  el("area").value = item.area_m2;
  el("check-zoning").value = item.imar_durumu;
  selectView("check");
  if (zoom) map.setView([item.latitude,item.longitude],Math.max(map.getZoom(),10));
  runEstimate();
}

async function runEstimate() {
  error();
  const latitude = el("lat").value;
  const longitude = el("lon").value;
  const source = state.listing;
  const query = parameters({latitude,longitude,zoning:el("check-zoning").value,area_m2:el("area").value,asking_tl:el("asking").value});
  try {
    const data = await api(`/api/estimate?${query}`);
    if (latitude !== el("lat").value || longitude !== el("lon").value) return;
    state.estimate = data;
    setPin(data.latitude,data.longitude);
    const box = element("div",undefined,"estimate");
    const label = source && source.latitude===data.latitude && source.longitude===data.longitude ? `${source.parcel_id} · listed ${source.ilan_tarihi}` : `${data.zoning} · ${fmt(data.area_m2,1)} m²`;
    box.append(element("div",label,"hint"),element("strong",`${fmt(data.predicted_tl_m2,1)} TL/m²`,"total"),
      element("div",`${fmt(data.predicted_total_tl)} TL estimated total · Index ${fmt(data.price_index,1)}`));
    if (data.assessment) box.append(element("div",`${data.assessment} · asking ${fmt(data.asking_tl_m2,1)} TL/m² (${signed(data.asking_gap_pct)}%)`,
      data.assessment==="Underpriced"?"good":data.assessment==="Overpriced"?"bad":""));
    if (state.scenario) box.append(element("div",`${signed(data.scenario_delta_tl_m2,2)} TL/m² versus no new facility`));
    el("estimate-output").replaceChildren(box);
    el("estimate-download").hidden = false;
    const popup = element("div");
    popup.append(element("div",label,"popup-title"),element("div",`${fmt(data.predicted_tl_m2,1)} TL/m² · Index ${fmt(data.price_index,1)}`));
    if (data.assessment) popup.append(element("div",`${data.assessment} · asking ${fmt(data.asking_tl_m2,1)} TL/m²`));
    state.pin.bindPopup(popup).openPopup();
  } catch (e) {
    el("estimate-output").replaceChildren();
    el("estimate-download").hidden = true;
    error(e.message);
  }
}

function modelDisplay(meta) {
  el("model-version").textContent = `Model ${meta.version} · ${meta.date.slice(0,10)}`;
  const { best_model:family,cv_metrics:cv,training_rows:n,fixed_holdout_metrics:hold } = meta.model;
  const card = element("div",undefined,"estimate");
  card.append(element("strong",`${family} · ${n} baseline listings`),
    element("div",`5 spatial folds · R² ${fmt(cv.r2,3)} · RMSE ${fmt(cv.rmse)} TL/m²`));
  if (meta.comparison) {
    const values = meta.comparison;
    card.append(element("p",`${values.training_rows} total training rows · ${values.fixed_test_n} fixed test observations`));
    const table = element("table");
    for (const [index,row] of [["Metric","Before","After"],["R²",fmt(values.before.r2,3),fmt(values.after.r2,3)],
      ["RMSE (TL/m²)",fmt(values.before.rmse),fmt(values.after.rmse)],["MAE (TL/m²)",fmt(values.before.mae),fmt(values.after.mae)]].entries()) {
      const tr=element("tr");
      row.forEach(value => tr.append(element(index===0?"th":"td",value)));
      table.append(tr);
    }
    card.append(table);
  } else card.append(element("div",`Update benchmark · ${hold.test_n} locked test listings`));
  el("model-details").replaceChildren(card);
  el("reset-model").hidden = meta.version === "v1.0.0";
}

async function switchModel(version) {
  const data = await api(`/api/meta?version=${encodeURIComponent(version)}`);
  state.version = version;
  sessionStorage.setItem("konya-version",version);
  metadata = data;
  modelDisplay(data);
  await refresh();
}

async function upload(event) {
  event.preventDefault();
  error();
  el("retrain-button").disabled = true;
  el("update-status").textContent = "Validating files…";
  const form = new FormData(event.target);
  for (const key of ["listings","features"]) if (!form.get(key).name) form.delete(key);
  form.set("version",state.version);
  try {
    const job = await api("/api/retrain",{method:"POST",body:form});
    el("update-status").textContent = "Retraining and scoring the locked spatial test set…";
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      await new Promise(resolve=>setTimeout(resolve,800));
      const status = await api(`/api/retrain/${job.job}`);
      if (status.state === "complete") {
        el("update-status").textContent = `Updated ${status.date}. The map now uses the new model.`;
        await switchModel(status.version);
        return;
      }
    }
    throw new Error("The model update is still running. Retry after it finishes.");
  } catch (e) {
    el("update-status").textContent = e.message;
    error(e.message);
  } finally { el("retrain-button").disabled = false; }
}

async function runScenario(event) {
  event.preventDefault();
  error();
  const lat = Number(el("scenario-lat").value), lon = Number(el("scenario-lon").value);
  const old = state.scenario;
  state.scenario = {type:el("scenario-type").value,lat,lon};
  try { await api(`/api/grid?${gridParams()}`); }
  catch (e) { state.scenario=old; error(e.message); return; }
  if (state.scenarioPin) state.scenarioPin.remove();
  state.scenarioPin = L.circleMarker([lat,lon],{radius:9,weight:3,color:"#672c5c",fillColor:"#dca0bf",fillOpacity:1}).addTo(map);
  state.scenarioPin.bindTooltip(state.scenario.type === "park" ? "Proposed park" : "Proposed transit station");
  el("surface").value = "delta";
  el("value-class").value = "";
  el("scenario-clear").hidden = false;
  await refresh();
}

function listen() {
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>selectView(button.dataset.view)));
  el("search-form").addEventListener("submit",event=>{event.preventDefault();refresh();});
  ["surface","zoning","value-class"].forEach(id=>el(id).addEventListener("change",refresh));
  el("check-form").addEventListener("submit",event=>{event.preventDefault();runEstimate();});
  el("scenario-form").addEventListener("submit",runScenario);
  el("upload-form").addEventListener("submit",upload);
  el("reset-model").addEventListener("click",()=>switchModel("v1.0.0").catch(e=>error(e.message)));
  el("reset-view").addEventListener("click",()=>map.fitBounds(boundary.getBounds(),{padding:[18,18]}));
  el("scenario-pick").addEventListener("click",()=> {
    state.picking = !state.picking;
    el("scenario-pick").textContent = state.picking ? "Click a location…" : "Pick on map";
  });
  el("scenario-clear").addEventListener("click",()=> {
    state.scenario = null;
    if (state.scenarioPin) state.scenarioPin.remove();
    el("surface").value = "price";
    el("scenario-output").replaceChildren();
    el("scenario-clear").hidden = true;
    refresh();
  });
  el("estimate-download").addEventListener("click",()=> {
    const {features,...estimate} = state.estimate;
    const values = {...estimate,...features};
    const row = Object.values(values).map(value=>typeof value==="string" ? `"${value.replaceAll('"','""')}"` : value ?? "");
    const csv = new Blob([Object.keys(values).join(","),"\r\n",row.join(","),"\r\n"],{type:"text/csv;charset=utf-8"});
    const url = URL.createObjectURL(csv);
    const link = element("a");
    link.href = url;
    link.download = "location_valuation.csv";
    link.click();
    setTimeout(()=>URL.revokeObjectURL(url),500);
  });
}

async function init() {
  try { metadata = await api(`/api/meta?version=${encodeURIComponent(state.version)}`); }
  catch (e) {
    if (state.version === "v1.0.0") throw e;
    state.version = "v1.0.0";
    sessionStorage.removeItem("konya-version");
    metadata = await api("/api/meta");
  }
  Object.keys(metadata.model.reference_area_by_zoning).forEach(zoning=>{
    ["zoning","check-zoning","filter-zoning"].forEach(id=>option(el(id),zoning));
  });
  metadata.class_names.forEach((label,i)=>["value-class","listing-class"].forEach(id=>option(el(id),String(i),label)));
  el("zoning").value = metadata.model.grid.reference_zoning;
  el("check-zoning").value = el("zoning").value;
  el("area").value = metadata.model.grid.reference_area_m2;
  modelDisplay(metadata);
  map = L.map("map",{preferCanvas:true,attributionControl:false,minZoom:5,maxZoom:17});
  map.createPane("surface").style.zIndex = "270";
  map.createPane("local-context").style.zIndex = "320";
  boundary = L.geoJSON(metadata.boundary,{style:{color:"#244638",weight:1.3,opacity:.9,fillColor:"#d7e2d3",fillOpacity:.34},interactive:false}).addTo(map);
  map.fitBounds(boundary.getBounds(),{padding:[18,18]});
  L.control.scale({imperial:false}).addTo(map);
  markers = L.layerGroup().addTo(map);
  api("/api/context").then(geo=>L.geoJSON(geo,{pane:"local-context",interactive:false,
    style:f=>f.properties.layer==="waterway"?{color:"#6f9dab",weight:1,opacity:.65}:{color:"#5c584c",weight:.55,opacity:.38},
    pointToLayer:(_feature,location)=>L.circleMarker(location,{radius:3,color:"#254b40",fillOpacity:.7})}).addTo(map)).catch(()=>{});
  map.on("click",event=>{
    const {lat,lng:lon} = event.latlng;
    if (state.picking) {
      el("scenario-lat").value = lat.toFixed(6);
      el("scenario-lon").value = lon.toFixed(6);
      state.picking = false;
      el("scenario-pick").textContent = "Pick on map";
      return;
    }
    state.listing = null;
    el("lat").value = lat.toFixed(6);
    el("lon").value = lon.toFixed(6);
    el("asking").value = "";
    el("check-zoning").value = el("zoning").value;
    el("area").value = metadata.model.reference_area_by_zoning[el("zoning").value];
    selectView("check");
    runEstimate();
  });
  listen();
  await refresh();
}

init().catch(e=>error(e.message));
