"use strict";
// The Studio's transport: `studioApi.call(method, body)` runs one method of
// anchorsfactory/studio/api.py and resolves to its JSON answer. The local
// server answers /api/<method>; the web Studio (web/) sets `window.studioApi`
// to a Pyodide worker before app.js runs, and this file is not loaded there.
window.studioApi = window.studioApi || {
  kind: "http",
  async call(method, body){
    const get = method === "state" || method === "allglyphs";
    const res = await fetch("/api/" + method, get ? {} : {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {}),
    });
    return res.json();
  },
  // a dropped font: [{path, file}] with paths relative to the drop root
  async loadFont(name, collected){
    const files = [];
    for(const c of collected) files.push({path: c.path, data: await fileToB64(c.file)});
    return this.call("font", {name, files});
  },
  // startup progress (the worker reports Python loading; nothing to say here)
  onStatus(){},
};

async function fileToB64(file){
  const bytes = new Uint8Array(await file.arrayBuffer()); let bin = ""; const step = 0x8000;
  for(let i = 0; i < bytes.length; i += step) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  return btoa(bin);
}
