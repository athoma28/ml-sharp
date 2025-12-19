"""Minimal web app for generating a motion video from a single image.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

import asyncio
import base64
import contextlib
import dataclasses
import os
from pathlib import Path
import secrets
import time
import uuid
from typing import Any, Literal

from .sharp_pan import generate_sharp_swipe_mp4


HTML_INDEX = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>SHARP — Motion Video</title>
    <style>
      :root{
        --bg0:#0b1220;
        --bg1:#0e1a30;
        --card:#101b31cc;
        --card2:#0f172aee;
        --txt:#e6ecff;
        --muted:#a9b4d6;
        --line:#233154;
        --accent:#7c5cff;
        --accent2:#27e3c2;
        --danger:#ff4d6d;
        --shadow: 0 18px 50px rgba(0,0,0,.35);
        --radius: 16px;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
        --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, \"Apple Color Emoji\", \"Segoe UI Emoji\";
      }
      @media (prefers-color-scheme: light) {
        :root{
          --bg0:#f5f7ff;
          --bg1:#eef2ff;
          --card:#ffffffcc;
          --card2:#ffffffee;
          --txt:#0b1020;
          --muted:#4b556e;
          --line:#d9e0f6;
          --shadow: 0 18px 50px rgba(5,15,40,.15);
        }
      }
      *{ box-sizing:border-box; }
      html,body{ height:100%; }
      body{
        margin:0;
        font-family:var(--sans);
        color:var(--txt);
        background:
          radial-gradient(1200px 600px at 15% 10%, rgba(124,92,255,.35), transparent 60%),
          radial-gradient(900px 550px at 85% 15%, rgba(39,227,194,.28), transparent 55%),
          linear-gradient(180deg, var(--bg0), var(--bg1));
      }
      a{ color:inherit; }
      .wrap{
        max-width: 1120px;
        margin: 0 auto;
        padding: 28px 18px 50px;
      }
      header{
        display:flex;
        align-items:flex-end;
        justify-content:space-between;
        gap:18px;
        margin-bottom: 18px;
      }
      .brand h1{
        margin:0;
        font-size: 22px;
        letter-spacing: .2px;
      }
      .brand p{
        margin:6px 0 0;
        color:var(--muted);
        font-size: 13px;
        max-width: 720px;
      }
      .pill{
        font-family: var(--mono);
        font-size: 12px;
        padding: 8px 10px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: rgba(255,255,255,.04);
        color: var(--muted);
        white-space:nowrap;
      }
      .grid{
        display:grid;
        grid-template-columns: 1.1fr .9fr;
        gap: 16px;
      }
      @media (max-width: 920px){
        .grid{ grid-template-columns: 1fr; }
      }
      .card{
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: var(--card);
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow);
        overflow:hidden;
      }
      .card .hd{
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
        background: var(--card2);
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap: 10px;
      }
      .card .hd h2{
        margin:0;
        font-size: 14px;
        letter-spacing: .2px;
      }
      .card .bd{
        padding: 16px;
      }
      .row{
        display:grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
      }
      @media (max-width: 540px){
        .row{ grid-template-columns: 1fr; }
      }
      label{
        display:block;
        font-size: 12px;
        color: var(--muted);
        margin-bottom: 6px;
      }
      input[type=file], input[type=number], select{
        width:100%;
        padding: 10px 10px;
        border-radius: 12px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.05);
        color: var(--txt);
        outline: none;
      }
      input[type=number]::-webkit-outer-spin-button,
      input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
      input[type=range]{ width:100%; }
      .slider{
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 10px 10px 8px;
        background: rgba(255,255,255,.04);
      }
      .slider .top{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        margin-bottom: 6px;
      }
      .slider .val{
        font-family: var(--mono);
        font-size: 12px;
        color: var(--txt);
      }
      .hint{
        margin-top: 8px;
        font-size: 12px;
        color: var(--muted);
      }
      .btns{
        margin-top: 12px;
        display:flex;
        gap: 10px;
        flex-wrap: wrap;
      }
      .check{
        display:flex;
        align-items:center;
        gap: 8px;
        margin-top: 10px;
        font-size: 13px;
        color: var(--txt);
      }
      .check input{
        width:auto;
        margin:0;
        accent-color: var(--accent);
      }
      .dropzone{
        border: 1.5px dashed var(--line);
        border-radius: 14px;
        padding: 14px;
        background: rgba(255,255,255,.04);
        cursor: pointer;
        display:flex;
        align-items:center;
        gap: 10px;
        min-height: 64px;
        transition: border-color .15s ease, background .15s ease;
      }
      .dropzone .title{
        font-weight: 600;
        font-size: 13px;
      }
      .dropzone .hint{
        margin:0;
      }
      .dropzone .thumb{
        width: 44px;
        height: 44px;
        border-radius: 10px;
        overflow:hidden;
        background: rgba(255,255,255,.08);
        display:flex;
        align-items:center;
        justify-content:center;
        font-size: 11px;
        color: var(--muted);
      }
      .dropzone.active{
        border-color: var(--accent);
        background: rgba(124,92,255,.08);
      }
      button{
        border: 1px solid var(--line);
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(124,92,255,.85), rgba(39,227,194,.5));
        color: white;
        padding: 10px 14px;
        font-weight: 600;
        cursor: pointer;
      }
      button.secondary{
        background: rgba(255,255,255,.06);
        color: var(--txt);
      }
      button:disabled{
        opacity: .55;
        cursor: not-allowed;
      }
      details{
        margin-top: 10px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(255,255,255,.03);
      }
      summary{
        cursor:pointer;
        padding: 10px 10px;
        font-size: 12px;
        color: var(--muted);
        list-style: none;
      }
      summary::-webkit-details-marker{ display:none; }
      details .bd2{ padding: 0 10px 10px; }

      .kv{
        display:flex;
        justify-content:space-between;
        gap: 10px;
        font-size: 12px;
        color: var(--muted);
        margin-top: 10px;
        border-top: 1px solid var(--line);
        padding-top: 10px;
      }
      .kv code{ font-family: var(--mono); color: var(--txt); }

      .prog{
        display:grid;
        gap: 10px;
      }
      .stage{
        display:grid;
        grid-template-columns: 1fr;
        gap: 6px;
        padding: 10px 10px 12px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(255,255,255,.03);
      }
      .stage .nm{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap: 10px;
        font-size: 12px;
        color: var(--muted);
      }
      .stage .nm strong{
        color: var(--txt);
        font-weight: 600;
      }
      progress{
        width:100%;
        height: 10px;
        border-radius: 999px;
        overflow: hidden;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.04);
      }
      progress::-webkit-progress-bar{
        background: rgba(255,255,255,.06);
      }
      progress::-webkit-progress-value{
        background: linear-gradient(90deg, var(--accent), var(--accent2));
      }
      progress::-moz-progress-bar{
        background: linear-gradient(90deg, var(--accent), var(--accent2));
      }

      .err{
        margin-top: 10px;
        padding: 10px 12px;
        border: 1px solid rgba(255,77,109,.35);
        background: rgba(255,77,109,.10);
        color: var(--txt);
        border-radius: 12px;
        font-size: 12px;
        display:none;
      }
      .media{
        display:grid;
        gap: 12px;
      }
      .viewer{
        margin-top: 12px;
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 12px;
        background: rgba(255,255,255,.03);
      }
      .viewer-head{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        margin-bottom: 10px;
      }
      .viewer-head .title{
        font-weight: 700;
        font-size: 13px;
      }
      .viewer-frame{
        position: relative;
        width:100%;
        aspect-ratio: 16/10;
        border-radius: 12px;
        overflow:hidden;
        border: 1px solid var(--line);
        background: rgba(0,0,0,.2);
      }
      .viewer-frame iframe{
        width:100%;
        height:100%;
        border:0;
      }
      .preview{
        width:100%;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: rgba(0,0,0,.12);
        aspect-ratio: 16/10;
        display:grid;
        place-items:center;
        overflow:hidden;
      }
      .preview img, .preview video{
        width:100%;
        height:100%;
        object-fit:contain;
        display:none;
      }
      .preview .ph{
        padding: 18px;
        color: var(--muted);
        font-size: 12px;
        text-align:center;
      }
      .dl{
        display:flex;
        gap:10px;
        flex-wrap: wrap;
        align-items:center;
        justify-content:space-between;
      }
      .dl a{
        font-family: var(--mono);
        font-size: 12px;
        color: var(--txt);
      }
      .small{
        font-size: 12px;
        color: var(--muted);
      }
    </style>
  </head>
  <body>
    <div class=\"wrap\">
      <header>
        <div class=\"brand\">
          <h1>SHARP motion video</h1>
          <p>Upload a single image and render a short camera-motion clip. CUDA runs the full 3DGS renderer; macOS/MPS or CPU uses a depth-parallax fallback.</p>
        </div>
        <div class=\"pill\" id=\"devicePill\">device: <span id=\"deviceText\">unknown</span></div>
      </header>

      <div class=\"grid\">
        <section class=\"card\">
          <div class=\"hd\">
            <h2>Render Settings</h2>
            <span class=\"pill\">fast, lightweight UI</span>
          </div>
          <div class=\"bd\">
            <form id=\"renderForm\">
              <div class=\"row\">
                <div>
                  <label for=\"image\">Image</label>
                  <div class=\"dropzone\" id=\"dropZone\">
                    <div class=\"thumb\" id=\"dropThumb\">IMG</div>
                    <div>
                      <div class=\"title\">Drop an image or click to browse</div>
                      <p class=\"hint\" id=\"dropHint\">JPEG / PNG / HEIC</p>
                    </div>
                  </div>
                  <input id=\"image\" type=\"file\" name=\"image\" accept=\"image/*\" required style=\"display:none\" />
                </div>
                <div>
                  <label for=\"trajectory_type\">Motion type</label>
                  <select id=\"trajectory_type\" name=\"trajectory_type\">
                    <option value=\"swipe\" selected>Swipe (left ↔ right)</option>
                    <option value=\"shake\">Shake (x then y)</option>
                    <option value=\"rotate\">Rotate (circle)</option>
                    <option value=\"rotate_forward\">Rotate + push (zoom)</option>
                  </select>
                </div>
              </div>

              <div class=\"row\" style=\"margin-top:10px\">
                <div>
                  <label for=\"render_max_side\">Render quality</label>
                  <select id=\"render_max_side\" name=\"render_max_side\">
                    <option value=\"0\">Full (use image resolution)</option>
                    <option value=\"1920\">High (max 1920px)</option>
                    <option value=\"1536\" selected>Balanced (max 1536px)</option>
                    <option value=\"1280\">Medium (max 1280px)</option>
                    <option value=\"960\">Social (max 960px)</option>
                    <option value=\"720\">Small (max 720px)</option>
                  </select>
                </div>
                <div>
                  <label for=\"fps\">FPS</label>
                  <input id=\"fps\" type=\"number\" name=\"fps\" value=\"30\" step=\"1\" min=\"6\" max=\"60\" />
                </div>
              </div>

              <div class=\"row\" style=\"margin-top:10px\">
                <div>
                  <label for=\"duration_s\">Duration (seconds)</label>
                  <input id=\"duration_s\" type=\"number\" name=\"duration_s\" value=\"4.0\" step=\"0.1\" min=\"0.2\" max=\"20\" />
                </div>
              </div>

              <div class=\"row\" style=\"margin-top:10px\">
                <div class=\"slider\">
                  <div class=\"top\">
                    <label for=\"motion_scale\" style=\"margin:0\">Motion amount</label>
                    <span class=\"val\" id=\"motion_scale_val\">0.20</span>
                  </div>
                  <input id=\"motion_scale\" type=\"range\" name=\"motion_scale\" min=\"0.05\" max=\"1.00\" step=\"0.01\" value=\"0.20\" />
                </div>
                <div class=\"slider\">
                  <div class=\"top\">
                    <label for=\"wobble_scale\" style=\"margin:0\">Wobble</label>
                    <span class=\"val\" id=\"wobble_scale_val\">0.25</span>
                  </div>
                  <input id=\"wobble_scale\" type=\"range\" name=\"wobble_scale\" min=\"0.00\" max=\"1.00\" step=\"0.01\" value=\"0.25\" />
                </div>
              </div>

              <details>
                <summary>Advanced motion controls</summary>
                <div class=\"bd2\">
                  <div class=\"row\">
                    <div class=\"slider\">
                      <div class=\"top\">
                        <label for=\"max_disparity\" style=\"margin:0\">Parallax strength</label>
                        <span class=\"val\" id=\"max_disparity_val\">0.08</span>
                      </div>
                      <input id=\"max_disparity\" type=\"range\" name=\"max_disparity\" min=\"0.01\" max=\"0.20\" step=\"0.005\" value=\"0.08\" />
                      <div class=\"hint\">Base disparity used by the trajectory model; combined with “Motion amount”.</div>
                    </div>
                    <div class=\"slider\">
                      <div class=\"top\">
                        <label for=\"max_zoom\" style=\"margin:0\">Zoom (rotate+push)</label>
                        <span class=\"val\" id=\"max_zoom_val\">0.15</span>
                      </div>
                      <input id=\"max_zoom\" type=\"range\" name=\"max_zoom\" min=\"0.00\" max=\"0.40\" step=\"0.01\" value=\"0.15\" />
                      <div class=\"hint\">Most visible on “Rotate + push”.</div>
                    </div>
                  </div>

                  <div class=\"row\" style=\"margin-top:10px\">
                    <div class=\"slider\">
                      <div class=\"top\">
                        <label for=\"num_repeats\" style=\"margin:0\">Repeats</label>
                        <span class=\"val\" id=\"num_repeats_val\">1</span>
                      </div>
                      <input id=\"num_repeats\" type=\"range\" name=\"num_repeats\" min=\"1\" max=\"4\" step=\"1\" value=\"1\" />
                      <div class=\"hint\">Loops the motion pattern within the clip.</div>
                    </div>
                    <div class=\"slider\">
                      <div class=\"top\">
                        <label for=\"max_side\" style=\"margin:0\">Max input side (fallback)</label>
                        <span class=\"val\" id=\"max_side_val\">1536</span>
                      </div>
                      <input id=\"max_side\" type=\"range\" name=\"max_side\" min=\"640\" max=\"2048\" step=\"64\" value=\"1536\" />
                      <div class=\"hint\">Limits memory on MPS/CPU; CUDA ignores this (uses full res).</div>
                    </div>
                  </div>
                </div>
              </details>

              <div class=\"row\" style=\"margin-top:10px\">
                <div>
                  <label for=\"output_mode\">Outputs</label>
                  <select id=\"output_mode\" name=\"output_mode\">
                    <option value=\"depth\" selected>Depth MP4 only</option>
                    <option value=\"ply\">PLY only</option>
                    <option value=\"both\">Both MP4 + PLY</option>
                  </select>
                  <p class=\"hint\">“Depth MP4” forces the fast fallback render; “PLY” runs full SHARP to export 3DGS; “Both” does both.</p>
                </div>
              </div>

              <div class=\"btns\">
                <button id=\"goBtn\" type=\"submit\">Generate MP4</button>
                <button class=\"secondary\" id=\"resetBtn\" type=\"button\">Reset</button>
              </div>
              <div class=\"err\" id=\"errBox\"></div>
              <div class=\"kv\">
                <div>endpoint <code>/jobs</code></div>
                <div>status <code id=\"statusText\">idle</code></div>
              </div>
            </form>
          </div>
        </section>

        <section class=\"card\">
          <div class=\"hd\">
            <h2>Progress & Preview</h2>
            <span class=\"pill\" id=\"jobPill\">job: <span id=\"jobId\">–</span></span>
          </div>
          <div class=\"bd\">
            <div class=\"prog\" id=\"prog\">
              <div class=\"stage\">
                <div class=\"nm\"><strong>Overall</strong><span class=\"val\" id=\"overall_val\">0%</span></div>
                <progress id=\"p_overall\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>Load</strong><span class=\"val\" id=\"s_load\">–</span></div>
                <progress id=\"p_load\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>Model</strong><span class=\"val\" id=\"s_inference\">–</span></div>
                <progress id=\"p_inference\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>Trajectory</strong><span class=\"val\" id=\"s_trajectory\">–</span></div>
                <progress id=\"p_trajectory\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>Render</strong><span class=\"val\" id=\"s_render\">–</span></div>
                <progress id=\"p_render\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>PLY export</strong><span class=\"val\" id=\"s_ply\">–</span></div>
                <progress id=\"p_ply\" value=\"0\" max=\"1\"></progress>
              </div>
              <div class=\"stage\">
                <div class=\"nm\"><strong>Finalize</strong><span class=\"val\" id=\"s_finalize\">–</span></div>
                <progress id=\"p_finalize\" value=\"0\" max=\"1\"></progress>
              </div>
            </div>

            <div class=\"media\" style=\"margin-top:12px\">
              <div class=\"preview\" id=\"preview\">
                <div class=\"ph\" id=\"ph\">Select an image to preview, then generate a clip.</div>
                <img id=\"imgPrev\" alt=\"Image preview\" />
                <video id=\"vidPrev\" controls playsinline></video>
              </div>
              <div class=\"dl\">
                <div class=\"small\" id=\"detailText\">–</div>
                <div style=\"display:flex;gap:10px;flex-wrap:wrap;align-items:center\">
                  <a id=\"downloadLink\" href=\"#\" style=\"display:none\">download mp4</a>
                  <a id=\"downloadPlyLink\" href=\"#\" style=\"display:none\">download ply</a>
                </div>
              </div>
              <div class=\"viewer\" id=\"viewerBlock\" style=\"display:none\">
                <div class=\"viewer-head\">
                  <div>
                    <div class=\"title\">Gaussian splat viewer</div>
                    <div class=\"small\">Loads the exported .ply into the Spark viewer.</div>
                  </div>
                  <button class=\"secondary\" type=\"button\" id=\"openViewerBtn\">Open viewer</button>
                </div>
                <div class=\"viewer-frame\">
                  <iframe id=\"splatFrame\" title=\"Gaussian splat viewer\" allowfullscreen></iframe>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);

      const stageIds = [\"load\",\"inference\",\"trajectory\",\"render\",\"ply\",\"finalize\"];
      function setErr(msg){
        const box = $(\"errBox\");
        if(!msg){
          box.style.display = \"none\";
          box.textContent = \"\";
          return;
        }
        box.style.display = \"block\";
        box.textContent = msg;
      }
      function setStatus(txt){ $(\"statusText\").textContent = txt; }

      function fmtPct(v){
        if(!isFinite(v)) return \"–\";
        return Math.round(v*100) + \"%\";
      }

      function setProgress(stage, value, label){
        const p = $(\"p_\"+stage);
        if(p) p.value = Math.max(0, Math.min(1, value));
        const s = $(\"s_\"+stage);
        if(s) s.textContent = label || fmtPct(value);
      }
      function setOverall(value){
        $(\"p_overall\").value = Math.max(0, Math.min(1, value));
        $(\"overall_val\").textContent = fmtPct(value);
      }

      const fileInput = $(\"image\");
      const dropZone = $(\"dropZone\");
      const dropThumb = $(\"dropThumb\");
      const dropHint = $(\"dropHint\");
      const defaultDropThumb = \"IMG\";
      const defaultDropHint = \"JPEG / PNG / HEIC\";
      const downloadLink = $(\"downloadLink\");
      const downloadPlyLink = $(\"downloadPlyLink\");
      const viewerBlock = $(\"viewerBlock\");
      const splatFrame = $(\"splatFrame\");
      const openViewerBtn = $(\"openViewerBtn\");

      function setFile(file){
        if(!file) return;
        if(!file.type || !file.type.startsWith(\"image/\")){
          setErr(\"Please drop an image file (jpg/png/heic).\");
          return;
        }
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        dropHint.textContent = file.name;
        const ext = (file.type.split(\"/\")[1] || \"IMG\").slice(0, 4).toUpperCase();
        dropThumb.textContent = ext || defaultDropThumb;
        fileInput.dispatchEvent(new Event(\"change\", { bubbles: true }));
      }

      function resetDropUi(){
        dropThumb.textContent = defaultDropThumb;
        dropHint.textContent = defaultDropHint;
        dropZone.classList.remove(\"active\");
      }

      dropZone.addEventListener(\"click\", () => fileInput.click());
      [\"dragenter\",\"dragover\"].forEach((evt) => {
        dropZone.addEventListener(evt, (e) => {
          e.preventDefault();
          dropZone.classList.add(\"active\");
        });
      });
      [\"dragleave\",\"drop\"].forEach((evt) => {
        dropZone.addEventListener(evt, (e) => {
          e.preventDefault();
          dropZone.classList.remove(\"active\");
        });
      });
      dropZone.addEventListener(\"drop\", (e) => {
        const files = e.dataTransfer?.files;
        if(files && files.length){
          setFile(files[0]);
        }
      });

      function bindSlider(id){
        const el = $(id);
        const out = $(id + \"_val\");
        const update = () => { out.textContent = el.value; };
        el.addEventListener(\"input\", update);
        update();
      }
      [\"motion_scale\",\"wobble_scale\",\"max_disparity\",\"max_zoom\",\"num_repeats\",\"max_side\"].forEach(bindSlider);

      function updateMotionEnables(){
        const t = $(\"trajectory_type\").value;
        const wobble = $(\"wobble_scale\");
        const maxZoom = $(\"max_zoom\");
        wobble.disabled = (t !== \"swipe\");
        maxZoom.disabled = (t !== \"rotate_forward\");
      }
      $(\"trajectory_type\").addEventListener(\"change\", updateMotionEnables);
      updateMotionEnables();

      $(\"resetBtn\").addEventListener(\"click\", () => {
        $(\"renderForm\").reset();
        resetDropUi();
        [\"motion_scale\",\"wobble_scale\",\"max_disparity\",\"max_zoom\",\"num_repeats\",\"max_side\"].forEach(bindSlider);
        updateMotionEnables();
        setErr(\"\");
        setStatus(\"idle\");
        $(\"jobId\").textContent = \"–\";
        $(\"detailText\").textContent = \"–\";
        stageIds.forEach(s => setProgress(s, 0, \"–\"));
        setOverall(0);
        downloadLink.style.display = \"none\";
        downloadPlyLink.style.display = \"none\";
        viewerBlock.style.display = \"none\";
        splatFrame.removeAttribute(\"src\");
        $(\"vidPrev\").removeAttribute(\"src\");
        $(\"vidPrev\").style.display = \"none\";
        $(\"ph\").style.display = \"block\";
      });

      $(\"image\").addEventListener(\"change\", (e) => {
        const f = e.target.files && e.target.files[0];
        if(!f){
          resetDropUi();
          return;
        }
        const url = URL.createObjectURL(f);
        $(\"imgPrev\").src = url;
        $(\"imgPrev\").style.display = \"block\";
        $(\"ph\").style.display = \"none\";
        $(\"vidPrev\").style.display = \"none\";
        downloadLink.style.display = \"none\";
        downloadPlyLink.style.display = \"none\";
        viewerBlock.style.display = \"none\";
        splatFrame.removeAttribute(\"src\");
        dropHint.textContent = f.name;
        const ext = (f.type.split(\"/\")[1] || defaultDropThumb).slice(0, 4).toUpperCase();
        dropThumb.textContent = ext || defaultDropThumb;
        setErr(\"\");
      });

      async function fetchJson(url){
        const res = await fetch(url, { headers: {\"Accept\":\"application/json\"} });
        if(!res.ok){
          const txt = await res.text().catch(() => \"\");
          throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
        }
        return await res.json();
      }

      async function poll(jobId){
        while(true){
          const st = await fetchJson(`/jobs/${jobId}`);
          if(st.device) $(\"deviceText\").textContent = st.device;
          $(\"detailText\").textContent = st.detail || \"–\";
          stageIds.forEach((k) => {
            const ps = (st.stages && st.stages[k]) || null;
            if(!ps) return;
            const label = ps.status === \"running\" ? fmtPct(ps.progress) : (ps.status || \"–\");
            setProgress(k, ps.progress || 0, label);
          });
          setOverall(st.overall_progress || 0);

          if(st.status === \"error\"){
            setStatus(\"error\");
            setErr(st.error || \"Render failed.\");
            $(\"goBtn\").disabled = false;
            return;
          }
          if(st.status === \"done\"){
            setStatus(\"done\");
            setErr(\"\");
            if(st.video_ready){
              const resultUrl = `/jobs/${jobId}/result`;
              const downloadUrl = `${resultUrl}?download=1`;
              downloadLink.href = downloadUrl;
              downloadLink.style.display = \"inline\";
              downloadLink.textContent = \"download mp4\";
              const vid = $(\"vidPrev\");
              vid.src = resultUrl;
              vid.style.display = \"block\";
              $(\"imgPrev\").style.display = \"none\";
              $(\"ph\").style.display = \"none\";
            }else{
              downloadLink.style.display = \"none\";
              const vid = $(\"vidPrev\");
              vid.removeAttribute(\"src\");
              vid.style.display = \"none\";
              $(\"imgPrev\").style.display = \"block\";
              $(\"ph\").style.display = \"block\";
            }
            if(st.ply_ready){
              const plyUrl = `/jobs/${jobId}/ply`;
              downloadPlyLink.href = `${plyUrl}?download=1`;
              downloadPlyLink.style.display = \"inline\";
              const viewerUrl = `/viewer/?url=${encodeURIComponent(plyUrl)}`;
              splatFrame.src = viewerUrl;
              viewerBlock.style.display = \"block\";
              openViewerBtn.onclick = () => {
                splatFrame.src = `${viewerUrl}&t=${Date.now()}`;
                splatFrame.scrollIntoView({ behavior: \"smooth\", block: \"center\" });
              };
            }else{
              downloadPlyLink.style.display = \"none\";
              viewerBlock.style.display = \"none\";
              splatFrame.removeAttribute(\"src\");
            }
            $(\"goBtn\").disabled = false;
            return;
          }
          await new Promise(r => setTimeout(r, 250));
        }
      }

      $(\"renderForm\").addEventListener(\"submit\", async (e) => {
        e.preventDefault();
        setErr(\"\");
        setStatus(\"starting\");
        $(\"goBtn\").disabled = true;
        downloadLink.style.display = \"none\";
        downloadPlyLink.style.display = \"none\";
        viewerBlock.style.display = \"none\";
        splatFrame.removeAttribute(\"src\");
        stageIds.forEach(s => setProgress(s, 0, \"–\"));
        setOverall(0);

        const fd = new FormData(e.target);
        if(!fileInput.files || !fileInput.files[0]){
          setErr(\"Please add an image (drop or browse).\");
          $(\"goBtn\").disabled = false;
          setStatus(\"idle\");
          return;
        }
        try{
          const res = await fetch(\"/jobs\", { method: \"POST\", body: fd });
          if(!res.ok){
            const txt = await res.text().catch(() => \"\");
            throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
          }
          const js = await res.json();
          const jobId = js.job_id;
          $(\"jobId\").textContent = jobId;
          setStatus(\"running\");
          await poll(jobId);
        }catch(err){
          setStatus(\"error\");
          setErr(err && err.message ? err.message : String(err));
          $(\"goBtn\").disabled = false;
        }
      });

      // Best-effort device hint, server will set it once a job starts.
      $(\"deviceText\").textContent = \"server-side\";
    </script>
  </body>
</html>
"""


def _read_password_file(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Password file is empty: {path}")
    return value


def _resolve_web_password(*, password: str | None, password_file: str | None) -> str | None:
    if password is not None:
        value = password.strip()
        if not value:
            raise RuntimeError("Provided password is empty.")
        return value

    if password_file is not None:
        return _read_password_file(password_file)

    env_password = os.getenv("SHARP_WEB_PASSWORD")
    if env_password:
        value = env_password.strip()
        if not value:
            raise RuntimeError("Env var SHARP_WEB_PASSWORD is empty.")
        return value

    env_password_file = os.getenv("SHARP_WEB_PASSWORD_FILE")
    if env_password_file:
        return _read_password_file(env_password_file)

    return None


def _is_authorized(auth_header: str | None, *, password: str) -> bool:
    if not auth_header:
        return False

    scheme, _, param = auth_header.partition(" ")
    scheme = scheme.strip().lower()
    param = param.strip()

    if scheme == "bearer":
        return secrets.compare_digest(param, password)

    if scheme == "basic":
        try:
            raw = base64.b64decode(param).decode("utf-8")
            _user, sep, pw = raw.partition(":")
            if not sep:
                return False
            return secrets.compare_digest(pw, password)
        except Exception:
            return False

    return False


def create_app(*, password: str | None = None, password_file: str | None = None):
    """Create the FastAPI app.

    Split into a factory function so the module can be imported even when
    FastAPI isn't installed.
    """

    try:
        from fastapi import FastAPI, File, Form, UploadFile
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is not installed. Install web deps with: "
            "pip install -r requirements-web.txt"
        ) from exc

    app = FastAPI(title="sharp-pan")

    web_password = _resolve_web_password(password=password, password_file=password_file)
    if web_password is not None:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request

        class _BasicAuthMiddleware(BaseHTTPMiddleware):
            def __init__(self, app: Any, *, password: str) -> None:
                super().__init__(app)
                self._password = password

            async def dispatch(self, request: Request, call_next: Any) -> Response:
                if _is_authorized(request.headers.get("authorization"), password=self._password):
                    return await call_next(request)
                headers = {
                    "WWW-Authenticate": 'Basic realm="sharp-web", charset="UTF-8"',
                    "Cache-Control": "no-store",
                }
                return Response(
                    content=b"Unauthorized.",
                    status_code=401,
                    media_type="text/plain",
                    headers=headers,
                )

        app.add_middleware(_BasicAuthMiddleware, password=web_password)

    root_dir = Path(__file__).resolve().parents[3]
    splat_dir = root_dir / "splat"
    if splat_dir.is_dir():
        app.mount("/splat", StaticFiles(directory=splat_dir, html=True), name="splat")
    spark_viewer_dir = root_dir / "spark" / "examples" / "viewer"
    if spark_viewer_dir.is_dir():
        app.mount(
            "/viewer",
            StaticFiles(directory=spark_viewer_dir, html=True),
            name="spark-viewer",
        )
    spark_dist_dir = root_dir / "spark" / "dist"
    if spark_dist_dir.is_dir():
        app.mount("/dist", StaticFiles(directory=spark_dist_dir), name="spark-dist")

    StageStatus = Literal["pending", "running", "done", "error"]

    STAGES: list[tuple[str, str, float]] = [
        ("load", "Load", 0.05),
        ("inference", "Model", 0.25),
        ("trajectory", "Trajectory", 0.05),
        ("render", "Render", 0.50),
        ("ply", "PLY export", 0.10),
        ("finalize", "Finalize", 0.05),
    ]

    @dataclasses.dataclass
    class _Stage:
        label: str
        progress: float = 0.0
        status: StageStatus = "pending"

    @dataclasses.dataclass
    class _Job:
        job_id: str
        created_at_s: float
        updated_at_s: float
        status: Literal["queued", "running", "done", "error"] = "queued"
        export_ply: bool = False
        output_mode: Literal["depth", "ply", "both"] = "depth"
        error: str | None = None
        detail: str | None = None
        device: str | None = None
        overall_progress: float = 0.0
        stages: dict[str, _Stage] = dataclasses.field(default_factory=dict)
        video_bytes: bytes | None = None
        ply_bytes: bytes | None = None

    class _JobStore:
        def __init__(self) -> None:
            import threading

            self._lock = threading.Lock()
            self._jobs: dict[str, _Job] = {}

        def create(
            self,
            *,
            export_ply: bool = False,
            output_mode: Literal["depth", "ply", "both"] = "depth",
        ) -> _Job:
            now = time.time()
            job_id = uuid.uuid4().hex[:12]
            stages = {k: _Stage(label=label) for (k, label, _w) in STAGES}
            job = _Job(
                job_id=job_id,
                created_at_s=now,
                updated_at_s=now,
                status="queued",
                export_ply=export_ply,
                output_mode=output_mode,
                stages=stages,
            )
            with self._lock:
                self._jobs[job_id] = job
            return job

        def get(self, job_id: str) -> _Job | None:
            with self._lock:
                return self._jobs.get(job_id)

        def cleanup(self, *, max_age_s: float = 60.0 * 30.0) -> None:
            now = time.time()
            with self._lock:
                drop = [
                    jid
                    for (jid, job) in self._jobs.items()
                    if (now - job.updated_at_s) > max_age_s
                ]
                for jid in drop:
                    self._jobs.pop(jid, None)

        def _recompute_overall(self, job: _Job) -> None:
            total = 0.0
            for stage_key, _label, weight in STAGES:
                st = job.stages.get(stage_key)
                if st is None:
                    continue
                total += float(weight) * float(st.progress)
            job.overall_progress = max(0.0, min(1.0, total))

        def update_stage(
            self,
            job_id: str,
            stage: str,
            *,
            progress: float | None = None,
            status: StageStatus | None = None,
            detail: str | None = None,
            device: str | None = None,
        ) -> None:
            now = time.time()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.updated_at_s = now
                if detail is not None:
                    job.detail = detail
                if device is not None:
                    job.device = device
                st = job.stages.get(stage)
                if st is not None:
                    if progress is not None:
                        st.progress = float(max(0.0, min(1.0, progress)))
                    if status is not None:
                        st.status = status
                self._recompute_overall(job)

        def set_status(
            self,
            job_id: str,
            status: Literal["queued", "running", "done", "error"],
            *,
            error: str | None = None,
            detail: str | None = None,
            video_bytes: bytes | None = None,
            device: str | None = None,
            ply_bytes: bytes | None = None,
        ) -> None:
            now = time.time()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.updated_at_s = now
                job.status = status
                if error is not None:
                    job.error = error
                if detail is not None:
                    job.detail = detail
                if video_bytes is not None:
                    job.video_bytes = video_bytes
                if device is not None:
                    job.device = device
                if ply_bytes is not None:
                    job.ply_bytes = ply_bytes

    store = _JobStore()
    job_queue: asyncio.Queue[tuple[str, bytes, dict[str, Any], bool, str]] = asyncio.Queue()

    async def _run_job(
        job_id: str, image_bytes: bytes, params: dict[str, Any], export_ply: bool, output_mode: str
    ) -> None:
        store.set_status(job_id, "running", detail="Starting render…")
        for stage_key, _label, _w in STAGES:
            store.update_stage(job_id, stage_key, progress=0.0, status="pending")
        if not export_ply:
            store.update_stage(job_id, "ply", progress=1.0, status="done", detail="Not requested.")
        if output_mode == "ply":
            store.update_stage(job_id, "render", progress=1.0, status="done", detail="Skipped (ply only).")

        def progress_cb(stage: str, progress: float, detail: str | None = None) -> None:
            try:
                store.update_stage(
                    job_id,
                    stage,
                    progress=progress,
                    status="running" if progress < 1.0 else "done",
                    detail=detail,
                )
            except Exception:
                pass

        try:
            if output_mode == "ply":
                # Ply only: run inference path but skip video rendering.
                _video_bytes, meta, ply_bytes = await asyncio.to_thread(
                    generate_sharp_swipe_mp4,
                    image_bytes,
                    render_video=False,
                    progress_cb=progress_cb,
                    return_meta=True,
                    return_ply=True,
                    force_depth_fallback=True,
                    **params,
                )
                video_bytes = None
            elif export_ply:
                video_bytes, meta, ply_bytes = await asyncio.to_thread(
                    generate_sharp_swipe_mp4,
                    image_bytes,
                    progress_cb=progress_cb,
                    return_meta=True,
                    return_ply=True,
                    force_depth_fallback=True,
                    **params,
                )
            else:
                video_bytes, meta = await asyncio.to_thread(
                    generate_sharp_swipe_mp4,
                    image_bytes,
                    progress_cb=progress_cb,
                    return_meta=True,
                    force_depth_fallback=True,
                    **params,
                )
                ply_bytes = None

            device = None
            if isinstance(meta, dict):
                device = meta.get("device", None)
            if export_ply:
                if ply_bytes is None:
                    raise RuntimeError("PLY generation failed.")
                size_mb = len(ply_bytes) / 1_000_000.0
                store.update_stage(job_id, "ply", progress=1.0, status="done", detail=f"{size_mb:.1f} MB")
            store.update_stage(job_id, "finalize", progress=1.0, status="done", device=device)
            detail_msg = "Done."
            if video_bytes:
                detail_msg = detail_msg + f" MP4 {len(video_bytes)/1_000_000.0:.1f} MB"
            if export_ply and ply_bytes is not None:
                detail_msg = detail_msg + f" + PLY {len(ply_bytes)/1_000_000.0:.1f} MB"
            store.set_status(
                job_id,
                "done",
                detail=detail_msg,
                video_bytes=video_bytes,
                device=device,
                ply_bytes=ply_bytes,
            )
        except Exception as exc:
            if export_ply:
                store.update_stage(job_id, "ply", progress=0.0, status="error")
            store.update_stage(job_id, "finalize", progress=0.0, status="error")
            store.set_status(job_id, "error", error=str(exc), detail="Render failed.")

    async def _worker() -> None:
        while True:
            job_id, image_bytes, params, export_ply, output_mode = await job_queue.get()
            try:
                await _run_job(job_id, image_bytes, params, export_ply, output_mode)
            except Exception as exc:  # pragma: no cover
                store.set_status(job_id, "error", error=str(exc), detail="Worker failed.")
            finally:
                job_queue.task_done()

    @app.on_event("startup")
    async def _start_worker() -> None:
        app.state._sharp_worker = asyncio.create_task(_worker())

    @app.on_event("shutdown")
    async def _stop_worker() -> None:
        task = getattr(app.state, "_sharp_worker", None)
        if task:
            task.cancel()
            with contextlib.suppress(Exception):
                await task

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML_INDEX

    @app.post("/pan")
    async def pan(
        image: UploadFile = File(...),
        duration_s: float = Form(4.0),
        fps: int = Form(30),
        motion_scale: float = Form(0.20),
        wobble_scale: float = Form(0.25),
        trajectory_type: str = Form("swipe"),
        max_disparity: float = Form(0.08),
        max_zoom: float = Form(0.15),
        num_repeats: int = Form(1),
        max_side: int = Form(1536),
        render_max_side: int = Form(1536),
    ):
        image_bytes = await image.read()
        video_bytes = generate_sharp_swipe_mp4(
            image_bytes,
            duration_s=duration_s,
            fps=fps,
            motion_scale=motion_scale,
            wobble_scale=wobble_scale,
            trajectory_type=trajectory_type,
            max_disparity=max_disparity,
            max_zoom=max_zoom,
            num_repeats=num_repeats,
            max_side=max_side,
            render_max_side=render_max_side,
        )

        headers = {"Content-Disposition": "attachment; filename=pan.mp4"}
        return Response(content=video_bytes, media_type="video/mp4", headers=headers)

    @app.post("/jobs")
    async def create_job(
        image: UploadFile = File(...),
        duration_s: float = Form(4.0),
        fps: int = Form(30),
        motion_scale: float = Form(0.20),
        wobble_scale: float = Form(0.25),
        trajectory_type: str = Form("swipe"),
        max_disparity: float = Form(0.08),
        max_zoom: float = Form(0.15),
        num_repeats: int = Form(1),
        max_side: int = Form(1536),
        render_max_side: int = Form(1536),
        export_ply: bool = Form(False),
        output_mode: str = Form("depth"),
    ) -> dict[str, Any]:
        store.cleanup()
        output_mode = str(output_mode).lower()
        allowed_modes = {"depth", "ply", "both"}
        if output_mode not in allowed_modes:
            raise ValueError(f"output_mode must be one of {sorted(allowed_modes)}")
        export_ply = bool(export_ply) or output_mode in {"ply", "both"}

        job = store.create(export_ply=export_ply, output_mode=output_mode)  # type: ignore[arg-type]
        job_id = job.job_id

        image_bytes = await image.read()
        params = {
            "duration_s": duration_s,
            "fps": fps,
            "motion_scale": motion_scale,
            "wobble_scale": wobble_scale,
            "trajectory_type": trajectory_type,
            "max_disparity": max_disparity,
            "max_zoom": max_zoom,
            "num_repeats": num_repeats,
            "max_side": max_side,
            "render_max_side": render_max_side,
        }
        await job_queue.put((job_id, image_bytes, params, export_ply, output_mode))
        store.set_status(job_id, "queued", detail="Queued.")
        return {"job_id": job_id}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        store.cleanup()
        job = store.get(job_id)
        if job is None:
            return {"status": "error", "error": "Unknown job id."}
        return {
            "job_id": job.job_id,
            "status": job.status,
            "error": job.error,
            "detail": job.detail,
            "device": job.device,
            "overall_progress": job.overall_progress,
            "export_ply": job.export_ply,
            "ply_ready": bool(job.ply_bytes),
            "video_ready": bool(job.video_bytes),
            "output_mode": job.output_mode,
            "stages": {
                k: {"label": st.label, "progress": st.progress, "status": st.status}
                for (k, st) in job.stages.items()
            },
        }

    @app.get("/jobs/{job_id}/result")
    def get_result(job_id: str, download: int = 0):
        job = store.get(job_id)
        if job is None or job.status != "done" or job.video_bytes is None:
            return Response(content=b"Not ready.", status_code=404)
        disposition = "attachment" if int(download) else "inline"
        headers = {"Content-Disposition": f"{disposition}; filename=pan.mp4"}
        return Response(content=job.video_bytes, media_type="video/mp4", headers=headers)

    @app.get("/jobs/{job_id}/ply")
    def get_ply(job_id: str, download: int = 0):
        job = store.get(job_id)
        if job is None or job.status != "done" or job.ply_bytes is None:
            return Response(content=b"Not ready.", status_code=404)
        disposition = "attachment" if int(download) else "inline"
        headers = {"Content-Disposition": f"{disposition}; filename=scene.ply"}
        return Response(content=job.ply_bytes, media_type="application/octet-stream", headers=headers)

    return app


# Convenience for `uvicorn sharp.web.app:app`
app = create_app()
