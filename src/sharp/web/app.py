"""Minimal web app for generating a motion video from a single image.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

import asyncio
import base64
import contextlib
import dataclasses
import io
import json
import os
from collections import deque
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
        --paper:#f6f4f1;
        --paper-strong:#ffffff;
        --ink:#111111;
        --muted:#5c5c5c;
        --line:#d7d4cf;
        --accent:#d40000;
        --accent-soft:rgba(212,0,0,.12);
        --shadow: 0 12px 24px rgba(0,0,0,.08);
        --radius: 12px;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
        --sans: \"Helvetica Neue\", \"Helvetica\", \"Univers\", \"Akzidenz-Grotesk\", \"Nimbus Sans L\", \"TeX Gyre Heros\", sans-serif;
      }
      *{ box-sizing:border-box; }
      html,body{ height:100%; }
      body{
        margin:0;
        font-family:var(--sans);
        color:var(--ink);
        background-image:
          linear-gradient(180deg, #faf9f7 0%, #f1f0ec 100%),
          linear-gradient(to right, rgba(17,17,17,.06) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(17,17,17,.06) 1px, transparent 1px);
        background-size: auto, 120px 120px, 120px 120px;
        background-attachment: fixed;
      }
      a{
        color:inherit;
        text-decoration:none;
        border-bottom: 1px solid rgba(17,17,17,.25);
      }
      a:hover{
        color: var(--accent);
        border-color: var(--accent);
      }
      .wrap{
        max-width: 1240px;
        margin: 0 auto;
        padding: 32px 20px 64px;
        display:grid;
        gap: 24px;
      }
      header{
        display:grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap:16px;
        align-items:end;
      }
      .brand{
        grid-column: 1 / span 8;
      }
      .meta{
        grid-column: 9 / span 4;
        display:flex;
        justify-content:flex-end;
        align-items:flex-end;
      }
      .eyebrow{
        font-size: 11px;
        letter-spacing: .3em;
        text-transform: uppercase;
        color: var(--muted);
        margin: 0 0 12px;
      }
      .brand h1{
        margin:0;
        font-size: clamp(32px, 4vw, 48px);
        line-height: 1;
        letter-spacing: -0.01em;
      }
      .brand p{
        margin:12px 0 0;
        color:var(--muted);
        font-size: 14px;
        max-width: 720px;
      }
      .pill{
        font-family: var(--mono);
        font-size: 11px;
        padding: 8px 12px;
        border: 1px solid var(--ink);
        text-transform: uppercase;
        letter-spacing: .18em;
        background: var(--paper-strong);
        white-space:nowrap;
      }
      .tabs{
        display:flex;
        gap: 16px;
        border-bottom: 1px solid var(--line);
        padding-bottom: 6px;
      }
      .tab-button{
        border: none;
        background: none;
        color: var(--muted);
        padding: 10px 2px;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .2em;
        cursor: pointer;
        border-bottom: 2px solid transparent;
      }
      .tab-button.active{
        color: var(--ink);
        border-color: var(--accent);
      }
      .tab-panel{
        display:none;
      }
      .tab-panel.active{
        display:grid;
        gap: 20px;
      }
      .basic-actions,
      .btns{
        margin-top: 12px;
        display:flex;
        gap: 10px;
        flex-wrap: wrap;
        align-items:center;
      }
      .basic-status{
        margin-top: 10px;
        font-size: 12px;
        color: var(--muted);
      }
      .basic-progress{
        margin-top: 10px;
      }
      .basic-progress-bar{
        height: 8px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(0,0,0,.05);
        overflow: hidden;
      }
      .basic-progress-fill{
        height: 100%;
        width: 0%;
        background: var(--accent);
        transition: width 0.2s ease;
      }
      .basic-queue{
        margin-top: 10px;
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 10px 12px;
        background: rgba(255,255,255,.7);
      }
      .basic-queue ul{
        list-style: none;
        padding: 6px 0 0;
        margin: 0;
        display: grid;
        gap: 6px;
        font-size: 12px;
      }
      .basic-queue li{
        display:flex;
        justify-content: space-between;
        gap: 8px;
        color: var(--muted);
      }
      .basic-queue .tag{
        font-family: var(--mono);
        color: var(--ink);
      }
      .basic-links{
        margin-top: 10px;
        display:flex;
        gap: 12px;
        flex-wrap: wrap;
        align-items: center;
        font-size: 12px;
      }
      .basic-links a{
        text-transform: uppercase;
        letter-spacing: .12em;
        font-size: 11px;
      }
      .grid{
        display:grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 16px;
      }
      .grid .card{
        grid-column: span 6;
      }
      .grid .card:nth-child(1){
        grid-column: 1 / span 7;
      }
      .grid .card:nth-child(2){
        grid-column: 8 / span 5;
      }
      @media (max-width: 980px){
        .grid{
          grid-template-columns: 1fr;
        }
        .grid .card{
          grid-column: auto;
        }
      }
      .card{
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: rgba(255,255,255,.86);
        box-shadow: var(--shadow);
        overflow:hidden;
      }
      .card .hd{
        padding: 16px 18px;
        border-bottom: 1px solid var(--line);
        background: rgba(255,255,255,.95);
        display:flex;
        align-items:flex-end;
        justify-content:space-between;
        gap: 10px;
      }
      .card .hd h2{
        margin:0;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: .18em;
      }
      .card .bd{
        padding: 18px;
      }
      .row{
        display:grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }
      @media (max-width: 600px){
        header{
          grid-template-columns: 1fr;
        }
        .brand,
        .meta{
          grid-column: 1 / -1;
        }
        .meta{
          justify-content:flex-start;
        }
        .row{
          grid-template-columns: 1fr;
        }
      }
      label{
        display:block;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .15em;
        color: var(--muted);
        margin-bottom: 6px;
      }
      input[type=file], input[type=number], select{
        width:100%;
        padding: 10px 10px;
        border-radius: 8px;
        border: 1px solid var(--ink);
        background: var(--paper-strong);
        color: var(--ink);
        outline: none;
        font-family: var(--mono);
      }
      input[type=number]::-webkit-outer-spin-button,
      input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
      input[type=range]{ width:100%; }
      .slider{
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 10px;
        background: rgba(255,255,255,.7);
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
        font-size: 11px;
        color: var(--ink);
      }
      .hint{
        margin-top: 8px;
        font-size: 12px;
        color: var(--muted);
      }
      .check{
        display:flex;
        align-items:center;
        gap: 8px;
        margin-top: 10px;
        font-size: 12px;
        color: var(--ink);
      }
      .check input{
        width:auto;
        margin:0;
        accent-color: var(--accent);
      }
      .dropzone{
        border: 1.5px dashed var(--ink);
        border-radius: 10px;
        padding: 12px;
        background: rgba(255,255,255,.7);
        cursor: pointer;
        display:flex;
        align-items:center;
        gap: 12px;
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
        border-radius: 8px;
        overflow:hidden;
        background: var(--paper);
        display:flex;
        align-items:center;
        justify-content:center;
        font-size: 11px;
        color: var(--muted);
        border: 1px solid var(--line);
      }
      .dropzone.active{
        border-color: var(--accent);
        background: var(--accent-soft);
      }
      .dropzone--basic{
        border-style: dotted;
        background: rgba(255,255,255,.9);
      }
      .dropzone--basic .title{
        font-weight: 500;
      }
      .dropzone--basic .hint{
        font-size: 11px;
      }
      .dropzone--basic .choose{
        font-family: var(--mono);
        text-transform: uppercase;
        letter-spacing: .14em;
        font-size: 10px;
        color: var(--muted);
      }
      button{
        border: 1px solid var(--ink);
        border-radius: 8px;
        background: var(--ink);
        color: white;
        padding: 10px 16px;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: .18em;
        text-transform: uppercase;
        cursor: pointer;
      }
      button.secondary{
        background: transparent;
        color: var(--ink);
      }
      button:disabled{
        opacity: .55;
        cursor: not-allowed;
      }
      details{
        margin-top: 10px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: rgba(255,255,255,.85);
      }
      summary{
        cursor:pointer;
        padding: 10px 12px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .16em;
        color: var(--muted);
        list-style: none;
      }
      summary::-webkit-details-marker{ display:none; }
      details .bd2{ padding: 0 12px 12px; }

      .kv{
        display:flex;
        justify-content:space-between;
        gap: 10px;
        font-size: 11px;
        color: var(--muted);
        margin-top: 12px;
        border-top: 1px solid var(--line);
        padding-top: 10px;
        text-transform: uppercase;
        letter-spacing: .14em;
      }
      .kv code{
        font-family: var(--mono);
        color: var(--ink);
        text-transform:none;
        letter-spacing: 0;
      }

      .prog{
        display:grid;
        gap: 12px;
      }
      .stage{
        display:grid;
        grid-template-columns: 1fr;
        gap: 6px;
        padding: 10px 12px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: rgba(255,255,255,.7);
      }
      .stage .nm{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap: 10px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .12em;
        color: var(--muted);
      }
      .stage .nm strong{
        color: var(--ink);
        font-weight: 600;
      }
      progress{
        width:100%;
        height: 8px;
        border-radius: 999px;
        overflow: hidden;
        border: 1px solid var(--line);
        background: rgba(0,0,0,.05);
      }
      progress::-webkit-progress-bar{
        background: rgba(0,0,0,.05);
      }
      progress::-webkit-progress-value{
        background: var(--accent);
      }
      progress::-moz-progress-bar{
        background: var(--accent);
      }

      .err{
        margin-top: 10px;
        padding: 10px 12px;
        border: 1px solid rgba(212,0,0,.45);
        background: rgba(212,0,0,.08);
        color: var(--ink);
        border-radius: 8px;
        font-size: 12px;
        display:none;
      }
      .media{
        display:grid;
        gap: 12px;
      }
      .viewer-card{
        margin: 18px 0;
      }
      .viewer{
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 12px;
        background: rgba(255,255,255,.85);
      }
      .viewer-head{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        margin-bottom: 12px;
      }
      .viewer-head .title{
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .18em;
      }
      .viewer-frame{
        position: relative;
        width:100%;
        height: clamp(420px, 65vh, 900px);
        border-radius: 10px;
        overflow:hidden;
        border: 1px solid var(--ink);
        background: #000;
      }
      .viewer-frame iframe{
        width:100%;
        height:100%;
        border:0;
      }
      .preview{
        width:100%;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.7);
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
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .12em;
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
          <p class=\"eyebrow\">Sharp</p>
          <h1>Motion video studio</h1>
          <p>Upload a single image and render a short camera-motion clip. CUDA runs the full 3DGS renderer; macOS/MPS or CPU uses a depth-parallax fallback.</p>
        </div>
        <div class=\"meta\">
          <div class=\"pill\" id=\"devicePill\">device: <span id=\"deviceText\">unknown</span></div>
        </div>
      </header>

      <div class=\"tabs\" role=\"tablist\">
        <button class=\"tab-button active\" id=\"tabBasic\" role=\"tab\" aria-selected=\"true\">Basic</button>
        <button class=\"tab-button\" id=\"tabDev\" role=\"tab\" aria-selected=\"false\">Dev</button>
      </div>

      <section class=\"tab-panel active\" id=\"basicPanel\" role=\"tabpanel\">
        <section class=\"card\">
          <div class=\"hd\">
            <h2>Basic export</h2>
            <span class=\"pill\">PLY only</span>
          </div>
          <div class=\"bd\">
            <form id=\"basicForm\">
              <label for=\"basicImage\">Image</label>
              <div class=\"dropzone dropzone--basic\" id=\"basicDropZone\">
                <div class=\"thumb\" id=\"basicDropThumb\">IMG</div>
                <div>
                  <div class=\"title\">Drop image here</div>
                  <p class=\"hint\">
                    <span id=\"basicDropHint\">click to</span>
                    <span class=\"choose\" id=\"basicDropHintChoose\">choose file</span>
                  </p>
                </div>
              </div>
              <input id=\"basicImage\" type=\"file\" name=\"image\" accept=\"image/*\" required style=\"display:none\" />
              <input type=\"hidden\" name=\"output_mode\" value=\"ply\" />
              <input type=\"hidden\" name=\"export_ply\" value=\"true\" />
              <div class=\"basic-actions\">
                <button id=\"basicGoBtn\" type=\"submit\">Generate PLY</button>
                <button class=\"secondary\" id=\"basicResetBtn\" type=\"button\">Reset</button>
              </div>
              <div class=\"basic-progress\" id=\"basicProgress\">
                <div class=\"basic-progress-bar\">
                  <div class=\"basic-progress-fill\" id=\"basicProgressFill\"></div>
                </div>
                <div class=\"basic-status\" id=\"basicStatus\">idle</div>
              </div>
              <div class=\"basic-links\">
                <a id=\"basicDownload\" href=\"#\" style=\"display:none\">download ply</a>
                <a href=\"https://sparkjs.dev/examples/#editor\" target=\"_blank\" rel=\"noreferrer\">Open Spark Editor</a>
              </div>
              <div class=\"basic-queue\">
                <div class=\"small\">Queue</div>
                <ul id=\"basicQueue\"></ul>
                <div class=\"small\" id=\"basicQueueMeta\">waiting: 0</div>
              </div>
            </form>
          </div>
        </section>
        <section class=\"card viewer-card\">
          <div class=\"hd\">
            <h2>Spark editor preview</h2>
            <span class=\"pill\">Editor</span>
          </div>
          <div class=\"bd\">
            <div class=\"viewer\" id=\"viewerBlockBasic\">
              <div class=\"viewer-head\">
                <div>
                  <div class=\"title\">Editor canvas</div>
                  <div class=\"small\">Loads the exported .ply when ready.</div>
                </div>
                <button class=\"secondary\" type=\"button\" id=\"openViewerBtnBasic\">Reload editor</button>
              </div>
              <div class=\"viewer-frame\">
                <iframe id=\"splatFrameBasic\" title=\"Gaussian splat viewer\" allowfullscreen></iframe>
              </div>
            </div>
          </div>
        </section>
      </section>

      <section class=\"tab-panel\" id=\"devPanel\" role=\"tabpanel\">
        <section class=\"card viewer-card\">
          <div class=\"hd\">
            <h2>Spark editor preview</h2>
            <span class=\"pill\">Editor</span>
          </div>
          <div class=\"bd\">
            <div class=\"viewer\" id=\"viewerBlock\">
              <div class=\"viewer-head\">
                <div>
                  <div class=\"title\">Editor canvas</div>
                  <div class=\"small\">Loads the exported .ply when ready.</div>
                </div>
                <button class=\"secondary\" type=\"button\" id=\"openViewerBtn\">Reload editor</button>
              </div>
              <div class=\"viewer-frame\">
                <iframe id=\"splatFrame\" title=\"Gaussian splat viewer\" allowfullscreen></iframe>
              </div>
            </div>
          </div>
        </section>

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
                    <option value=\"depth\">Depth MP4 only</option>
                    <option value=\"ply\" selected>PLY only</option>
                    <option value=\"both\">Both MP4 + PLY</option>
                  </select>
                  <p class=\"hint\">“Depth MP4” forces the fast fallback render; “PLY” runs full SHARP to export 3DGS; “Both” does both.</p>
                </div>
              </div>

              <div class=\"btns\">
                <button id=\"goBtn\" type=\"submit\">Generate output</button>
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
            </div>
          </div>
        </section>
        </div>
      </section>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);

      const tabBasic = $(\"tabBasic\");
      const tabDev = $(\"tabDev\");
      const basicPanel = $(\"basicPanel\");
      const devPanel = $(\"devPanel\");

      function setActiveTab(tab) {
        const isBasic = tab === \"basic\";
        tabBasic.classList.toggle(\"active\", isBasic);
        tabDev.classList.toggle(\"active\", !isBasic);
        tabBasic.setAttribute(\"aria-selected\", isBasic ? \"true\" : \"false\");
        tabDev.setAttribute(\"aria-selected\", isBasic ? \"false\" : \"true\");
        basicPanel.classList.toggle(\"active\", isBasic);
        devPanel.classList.toggle(\"active\", !isBasic);
      }

      tabBasic.addEventListener(\"click\", () => setActiveTab(\"basic\"));
      tabDev.addEventListener(\"click\", () => setActiveTab(\"dev\"));

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
      const splatFrame = $(\"splatFrame\");
      const splatFrameBasic = $(\"splatFrameBasic\");
      const openViewerBtn = $(\"openViewerBtn\");
      const openViewerBtnBasic = $(\"openViewerBtnBasic\");
      const defaultViewerUrl = \"/examples/editor/\";
      const basicForm = $(\"basicForm\");
      const basicImage = $(\"basicImage\");
      const basicDropZone = $(\"basicDropZone\");
      const basicDropThumb = $(\"basicDropThumb\");
      const basicDropHint = $(\"basicDropHint\");
      const basicDropHintChoose = $(\"basicDropHintChoose\");
      const basicDefaultDropThumb = \"IMG\";
      const basicDefaultDropHint = \"click to\";
      const basicProgress = $(\"basicProgress\");
      const basicProgressFill = $(\"basicProgressFill\");
      const basicGoBtn = $(\"basicGoBtn\");
      const basicResetBtn = $(\"basicResetBtn\");
      const basicStatus = $(\"basicStatus\");
      const basicDownload = $(\"basicDownload\");
      const basicQueue = $(\"basicQueue\");
      const basicQueueMeta = $(\"basicQueueMeta\");
      let basicFileName = \"scene\";
      let basicImageMeta = null;
      let basicImageObjectUrl = null;
      let metricsModel = { slope: 0, intercept: 12, sample_count: 0 };
      let basicEstimateRaf = null;
      let basicEstimateRunning = false;
      let basicEstimateDuration = null;
      let basicEstimateStart = 0;

      function withCacheBust(url){
        const sep = url.includes(\"?\") ? \"&\" : \"?\";
        return `${url}${sep}t=${Date.now()}`;
      }

      function setViewerSrc(url){
        [splatFrame, splatFrameBasic].forEach((frame) => {
          if(frame) frame.src = url;
        });
      }

      function bindViewerButton(button, frame, url){
        if(!button || !frame) return;
        button.onclick = () => {
          frame.src = withCacheBust(url);
        };
      }

      function bindViewerButtons(url){
        bindViewerButton(openViewerBtn, splatFrame, url);
        bindViewerButton(openViewerBtnBasic, splatFrameBasic, url);
      }

      bindViewerButtons(defaultViewerUrl);

      async function loadMetricsModel(){
        try{
          const res = await fetch(\"/metrics/estimate\", { headers: {\"Accept\":\"application/json\"} });
          if(!res.ok) return;
          const data = await res.json();
          if(data && typeof data === \"object\"){
            metricsModel = {
              slope: Number(data.slope) || 0,
              intercept: Number(data.intercept) || 12,
              sample_count: Number(data.sample_count) || 0,
            };
          }
        }catch(err){
          // Optional; fall back to defaults.
        }
      }

      function readBasicImageMeta(file){
        basicImageMeta = null;
        if(!file) return;
        if(basicImageObjectUrl) URL.revokeObjectURL(basicImageObjectUrl);
        basicImageObjectUrl = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
          basicImageMeta = {
            width: img.naturalWidth || 0,
            height: img.naturalHeight || 0,
          };
          if(basicImageObjectUrl){
            URL.revokeObjectURL(basicImageObjectUrl);
            basicImageObjectUrl = null;
          }
        };
        img.onerror = () => {
          basicImageMeta = null;
          if(basicImageObjectUrl){
            URL.revokeObjectURL(basicImageObjectUrl);
            basicImageObjectUrl = null;
          }
        };
        img.src = basicImageObjectUrl;
      }

      function estimateSeconds(meta){
        if(!meta || !meta.width || !meta.height) return null;
        const mpix = (meta.width * meta.height) / 1_000_000;
        const est = metricsModel.intercept + metricsModel.slope * mpix;
        if(!isFinite(est) || est <= 0) return null;
        return Math.max(1, Math.round(est * 2) / 2);
      }

      function formatSeconds(seconds){
        const rounded = Math.max(0.5, Math.round(seconds * 2) / 2);
        return `~${rounded.toFixed(1)}s remaining`;
      }

      function stopBasicEstimate(statusText){
        basicEstimateRunning = false;
        if(basicEstimateRaf){
          cancelAnimationFrame(basicEstimateRaf);
          basicEstimateRaf = null;
        }
        if(basicProgressFill){
          if(statusText === \"done\"){
            basicProgressFill.style.width = \"100%\";
          }else if(statusText === \"error\"){
            basicProgressFill.style.width = \"0%\";
          }else if(statusText){
            basicProgressFill.style.width = \"0%\";
          }
        }
        if(basicStatus && statusText){
          basicStatus.textContent = statusText;
        }
      }

      function startBasicEstimate(){
        stopBasicEstimate(\"\");
        if(!basicProgressFill || !basicStatus) return;
        const estimate = estimateSeconds(basicImageMeta);
        basicProgressFill.style.width = \"0%\";
        if(!estimate){
          basicStatus.textContent = \"processing...\";
          return;
        }
        basicEstimateDuration = estimate;
        basicEstimateStart = performance.now();
        basicEstimateRunning = true;

        const tick = () => {
          if(!basicEstimateRunning) return;
          const elapsed = (performance.now() - basicEstimateStart) / 1000;
          const progress = Math.min(elapsed / basicEstimateDuration, 1);
          basicProgressFill.style.width = `${(progress * 100).toFixed(1)}%`;
          if(progress >= 1){
            basicStatus.textContent = \"processing...\";
            basicEstimateRunning = false;
            return;
          }
          const remaining = Math.max(0, basicEstimateDuration - elapsed);
          basicStatus.textContent = formatSeconds(remaining);
          basicEstimateRaf = requestAnimationFrame(tick);
        };
        basicEstimateRaf = requestAnimationFrame(tick);
      }

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

      function updateBasicDropUi(file){
        if(!basicDropZone || !basicDropThumb || !basicDropHint) return;
        if(!file){
          resetBasicDropUi();
          return;
        }
        basicDropHint.textContent = file.name;
        const ext = (file.type.split(\"/\")[1] || \"IMG\").slice(0, 4).toUpperCase();
        basicDropThumb.textContent = ext || basicDefaultDropThumb;
        if (basicDropHintChoose) basicDropHintChoose.style.display = \"none\";
        basicDropZone.classList.remove(\"active\");
      }

      function resetBasicDropUi(){
        if(!basicDropZone || !basicDropThumb || !basicDropHint) return;
        basicDropThumb.textContent = basicDefaultDropThumb;
        basicDropHint.textContent = basicDefaultDropHint;
        if (basicDropHintChoose) basicDropHintChoose.style.display = \"inline\";
        basicDropZone.classList.remove(\"active\");
      }

      function setBasicFile(file){
        if(!file) return;
        if(!file.type || !file.type.startsWith(\"image/\")){
          setErr(\"Please drop an image file (jpg/png/heic).\");
          return;
        }
        const dt = new DataTransfer();
        dt.items.add(file);
        basicImage.files = dt.files;
        basicImage.dispatchEvent(new Event(\"change\", { bubbles: true }));
      }

      if (basicDropZone) {
        basicDropZone.addEventListener(\"click\", () => basicImage.click());
        [\"dragenter\",\"dragover\"].forEach((evt) => {
          basicDropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            basicDropZone.classList.add(\"active\");
          });
        });
        [\"dragleave\",\"drop\"].forEach((evt) => {
          basicDropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            basicDropZone.classList.remove(\"active\");
          });
        });
        basicDropZone.addEventListener(\"drop\", (e) => {
          const files = e.dataTransfer?.files;
          if(files && files.length){
            setBasicFile(files[0]);
          }
        });
      }

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
        setViewerSrc(defaultViewerUrl);
        bindViewerButtons(defaultViewerUrl);
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
        setViewerSrc(defaultViewerUrl);
        bindViewerButtons(defaultViewerUrl);
        dropHint.textContent = f.name;
        const ext = (f.type.split(\"/\")[1] || defaultDropThumb).slice(0, 4).toUpperCase();
        dropThumb.textContent = ext || defaultDropThumb;
        setErr(\"\");
      });

      basicImage.addEventListener(\"change\", (e) => {
        const f = e.target.files && e.target.files[0];
        if(!f){
          basicFileName = \"scene\";
          basicImageMeta = null;
          stopBasicEstimate(\"idle\");
          basicDownload.style.display = \"none\";
          resetBasicDropUi();
          setViewerSrc(defaultViewerUrl);
          bindViewerButtons(defaultViewerUrl);
          return;
        }
        updateBasicDropUi(f);
        readBasicImageMeta(f);
        basicFileName = f.name.replace(/\\.[^/.]+$/, \"\") || \"scene\";
        stopBasicEstimate(\"ready\");
        basicDownload.style.display = \"none\";
        setViewerSrc(defaultViewerUrl);
        bindViewerButtons(defaultViewerUrl);
      });

      basicResetBtn.addEventListener(\"click\", () => {
        basicForm.reset();
        basicFileName = \"scene\";
        basicImageMeta = null;
        stopBasicEstimate(\"idle\");
        basicDownload.style.display = \"none\";
        resetBasicDropUi();
        setViewerSrc(defaultViewerUrl);
        bindViewerButtons(defaultViewerUrl);
        fetchQueue();
      });

      async function fetchJson(url){
        const res = await fetch(url, { headers: {\"Accept\":\"application/json\"} });
        if(!res.ok){
          const txt = await res.text().catch(() => \"\");
          throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
        }
        return await res.json();
      }

      async function fetchQueue(){
        if(!basicQueue || !basicQueueMeta) return;
        try{
          const data = await fetchJson(\"/queue\");
          const entries = data.queue || [];
          basicQueue.innerHTML = \"\";
          if(entries.length === 0){
            const li = document.createElement(\"li\");
            li.textContent = \"empty\";
            basicQueue.appendChild(li);
          }else{
            entries.forEach((item) => {
              const li = document.createElement(\"li\");
              const name = item.image_name || \"scene\";
              li.innerHTML = `<span>${item.status}</span><span class=\"tag\">${name}.ply</span>`;
              basicQueue.appendChild(li);
            });
          }
          basicQueueMeta.textContent = `waiting: ${data.waiting_total || 0} across ${data.active_sessions || 0} queues`;
        }catch(err){
          basicQueueMeta.textContent = \"queue unavailable\";
        }
      }

      async function poll(jobId, options = {}){
        const useBasicProgress = options.useBasicProgress === true;
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
            if(useBasicProgress) stopBasicEstimate(\"error\");
            return;
          }
          if(st.status === \"done\"){
            setStatus(\"done\");
            setErr(\"\");
            if(useBasicProgress) stopBasicEstimate(\"done\");
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
              const safeName = (basicFileName || "scene").replace(/[^a-zA-Z0-9_-]+/g, "_");
              const plyUrl = `/jobs/${jobId}/ply/${safeName}.ply`;
              downloadPlyLink.href = `${plyUrl}?download=1`;
              downloadPlyLink.style.display = \"inline\";
              if (basicDownload) {
                basicDownload.href = `${plyUrl}?download=1`;
                basicDownload.style.display = \"inline\";
                basicDownload.textContent = `download ${basicFileName}.ply`;
              }
              const viewerUrl = `/examples/editor/?url=${encodeURIComponent(plyUrl)}`;
              setViewerSrc(viewerUrl);
              bindViewerButtons(viewerUrl);
            }else{
              downloadPlyLink.style.display = \"none\";
              setViewerSrc(defaultViewerUrl);
              bindViewerButtons(defaultViewerUrl);
              if (basicDownload) {
                basicDownload.style.display = \"none\";
              }
            }
            $(\"goBtn\").disabled = false;
            if (basicGoBtn) basicGoBtn.disabled = false;
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
        setViewerSrc(defaultViewerUrl);
        bindViewerButtons(defaultViewerUrl);
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

      basicForm.addEventListener(\"submit\", async (e) => {
        e.preventDefault();
        stopBasicEstimate(\"starting\");
        basicGoBtn.disabled = true;
        basicDownload.style.display = \"none\";
        fetchQueue();
        if(!basicImage.files || !basicImage.files[0]){
          stopBasicEstimate(\"please add an image\");
          basicGoBtn.disabled = false;
          fetchQueue();
          return;
        }
        try{
          const fd = new FormData(basicForm);
          const res = await fetch(\"/jobs\", { method: \"POST\", body: fd });
          if(!res.ok){
            const txt = await res.text().catch(() => \"\");
            throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
          }
          const js = await res.json();
          const jobId = js.job_id;
          $(\"jobId\").textContent = jobId;
          startBasicEstimate();
          await poll(jobId, { useBasicProgress: true });
        }catch(err){
          stopBasicEstimate(err && err.message ? err.message : String(err));
          basicGoBtn.disabled = false;
        }
      });

      // Best-effort device hint, server will set it once a job starts.
      $(\"deviceText\").textContent = \"server-side\";
      loadMetricsModel();
      setViewerSrc(defaultViewerUrl);
      bindViewerButtons(defaultViewerUrl);
      fetchQueue();
      setInterval(fetchQueue, 1000);
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


def _read_image_size(image_bytes: bytes, filename: str | None) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        if filename and filename.lower().endswith(".heic"):
            try:
                import pillow_heif

                heif = pillow_heif.open_heif(image_bytes, convert_hdr_to_8bit=True)
                img = heif.to_pillow()
                return img.width, img.height
            except Exception:
                return None, None

        img = Image.open(io.BytesIO(image_bytes))
        return img.width, img.height
    except Exception:
        return None, None


def create_app(*, password: str | None = None, password_file: str | None = None):
    """Create the FastAPI app.

    Split into a factory function so the module can be imported even when
    FastAPI isn't installed.
    """

    try:
        from fastapi import FastAPI, File, Form, Request, UploadFile
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import HTMLResponse, JSONResponse, Response
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

    import threading

    root_dir = Path(__file__).resolve().parents[3]
    metrics_path = root_dir / "data" / "web_metrics.json"
    metrics_lock = threading.Lock()

    def record_metrics(job: "_Job", finished_at_s: float) -> None:
        if job.requested_at_s is None:
            return
        entry = {
            "job_id": job.job_id,
            "requested_at_s": job.requested_at_s,
            "finished_at_s": finished_at_s,
            "duration_s": max(0.0, finished_at_s - job.requested_at_s),
            "image_name": job.image_name,
            "image_width": job.image_width,
            "image_height": job.image_height,
            "output_mode": job.output_mode,
            "device": job.device,
        }
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_lock:
            data: list[dict[str, Any]]
            if metrics_path.exists():
                try:
                    data = json.loads(metrics_path.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        data = []
                except Exception:
                    data = []
            else:
                data = []
            data.append(entry)
            metrics_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_metrics() -> list[dict[str, Any]]:
        with metrics_lock:
            if not metrics_path.exists():
                return []
            try:
                data = json.loads(metrics_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
            except Exception:
                return []
        return []

    def _fit_duration_model() -> dict[str, float]:
        data = _load_metrics()
        points: list[tuple[float, float]] = []
        for entry in data:
            try:
                width = float(entry.get("image_width") or 0)
                height = float(entry.get("image_height") or 0)
                duration = float(entry.get("duration_s") or 0)
            except (TypeError, ValueError):
                continue
            if width <= 0 or height <= 0 or duration <= 0:
                continue
            output_mode = str(entry.get("output_mode") or "ply").lower()
            if output_mode not in {"ply", "both"}:
                continue
            mpix = (width * height) / 1_000_000.0
            points.append((mpix, duration))

        if not points:
            return {"slope": 0.0, "intercept": 12.0, "sample_count": 0}
        if len(points) == 1:
            return {"slope": 0.0, "intercept": float(points[0][1]), "sample_count": 1}

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        var_x = sum((x - mean_x) ** 2 for x in xs)
        if var_x <= 1e-6:
            return {"slope": 0.0, "intercept": float(mean_y), "sample_count": len(points)}
        cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
        slope = cov_xy / var_x
        intercept = mean_y - slope * mean_x
        return {"slope": float(slope), "intercept": float(intercept), "sample_count": len(points)}

    session_cookie = "sharp_session"

    def get_session_id(request: Request) -> tuple[str, bool]:
        session_id = request.cookies.get(session_cookie)
        if session_id:
            return session_id, False
        return uuid.uuid4().hex, True

    queue_condition = asyncio.Condition()
    user_queues: dict[str, deque[tuple[str, bytes, dict[str, Any], bool, str]]] = {}
    user_order: deque[str] = deque()
    current_job_id: str | None = None
    current_session_id: str | None = None

    async def enqueue_job(
        session_id: str,
        payload: tuple[str, bytes, dict[str, Any], bool, str],
    ) -> None:
        async with queue_condition:
            queue = user_queues.setdefault(session_id, deque())
            queue.append(payload)
            if session_id not in user_order:
                user_order.append(session_id)
            queue_condition.notify()

    async def dequeue_job() -> tuple[str, tuple[str, bytes, dict[str, Any], bool, str]]:
        async with queue_condition:
            while True:
                while not user_order:
                    await queue_condition.wait()
                session_id = user_order.popleft()
                queue = user_queues.get(session_id)
                if not queue:
                    continue
                payload = queue.popleft()
                if queue:
                    user_order.append(session_id)
                return session_id, payload
    splat_dir = root_dir / "splat"
    if splat_dir.is_dir():
        app.mount("/splat", StaticFiles(directory=splat_dir, html=True), name="splat")
    spark_examples_dir = root_dir / "spark" / "examples"
    if spark_examples_dir.is_dir():
        app.mount(
            "/examples",
            StaticFiles(directory=spark_examples_dir, html=True),
            name="spark-examples",
        )
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
        output_mode: Literal["depth", "ply", "both"] = "ply"
        error: str | None = None
        detail: str | None = None
        device: str | None = None
        overall_progress: float = 0.0
        stages: dict[str, _Stage] = dataclasses.field(default_factory=dict)
        video_bytes: bytes | None = None
        ply_bytes: bytes | None = None
        requested_at_s: float | None = None
        image_width: int | None = None
        image_height: int | None = None
        image_name: str = "scene"
        metrics_recorded: bool = False
        session_id: str = ""

    class _JobStore:
        def __init__(self) -> None:
            import threading

            self._lock = threading.Lock()
            self._jobs: dict[str, _Job] = {}

        def create(
            self,
            *,
            export_ply: bool = False,
            output_mode: Literal["depth", "ply", "both"] = "ply",
            requested_at_s: float | None = None,
            image_width: int | None = None,
            image_height: int | None = None,
            image_name: str = "scene",
            session_id: str = "",
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
                requested_at_s=requested_at_s or now,
                image_width=image_width,
                image_height=image_height,
                image_name=image_name or "scene",
                session_id=session_id,
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
                if status == "done" and not job.metrics_recorded:
                    job.metrics_recorded = True
                    record_metrics(job, now)

    store = _JobStore()

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
        nonlocal current_job_id, current_session_id
        while True:
            session_id, payload = await dequeue_job()
            job_id, image_bytes, params, export_ply, output_mode = payload
            current_job_id = job_id
            current_session_id = session_id
            try:
                await _run_job(job_id, image_bytes, params, export_ply, output_mode)
            except Exception as exc:  # pragma: no cover
                store.set_status(job_id, "error", error=str(exc), detail="Worker failed.")
            finally:
                current_job_id = None
                current_session_id = None

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
    def index(request: Request):
        session_id, set_cookie = get_session_id(request)
        response = HTMLResponse(HTML_INDEX)
        if set_cookie:
            response.set_cookie(session_cookie, session_id, max_age=60 * 60 * 24 * 30)
        return response

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
        request: Request,
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
        output_mode: str = Form("ply"),
    ) -> Response:
        store.cleanup()
        session_id, set_cookie = get_session_id(request)
        output_mode = str(output_mode).lower()
        allowed_modes = {"depth", "ply", "both"}
        if output_mode not in allowed_modes:
            raise ValueError(f"output_mode must be one of {sorted(allowed_modes)}")
        export_ply = bool(export_ply) or output_mode in {"ply", "both"}

        image_bytes = await image.read()
        raw_name = Path(image.filename or "scene").name
        image_name = Path(raw_name).stem or "scene"
        image_width, image_height = _read_image_size(image_bytes, raw_name)
        requested_at_s = time.time()
        job = store.create(
            export_ply=export_ply,
            output_mode=output_mode,
            requested_at_s=requested_at_s,
            image_width=image_width,
            image_height=image_height,
            image_name=image_name,
            session_id=session_id,
        )  # type: ignore[arg-type]
        job_id = job.job_id
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
        await enqueue_job(session_id, (job_id, image_bytes, params, export_ply, output_mode))
        store.set_status(job_id, "queued", detail="Queued.")
        response = JSONResponse({"job_id": job_id})
        if set_cookie:
            response.set_cookie(session_cookie, session_id, max_age=60 * 60 * 24 * 30)
        return response

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

    @app.get("/queue")
    async def get_queue(request: Request) -> Response:
        session_id, set_cookie = get_session_id(request)
        async with queue_condition:
            queued_payloads = list(user_queues.get(session_id, deque()))
            queue_entries = []
            if current_session_id == session_id and current_job_id:
                job = store.get(current_job_id)
                queue_entries.append(
                    {
                        "job_id": current_job_id,
                        "status": "running",
                        "image_name": job.image_name if job else "scene",
                        "position": 0,
                    }
                )
            for idx, payload in enumerate(queued_payloads, start=1):
                job_id = payload[0]
                job = store.get(job_id)
                queue_entries.append(
                    {
                        "job_id": job_id,
                        "status": "queued",
                        "image_name": job.image_name if job else "scene",
                        "position": idx,
                    }
                )
            waiting_total = sum(len(q) for q in user_queues.values())
            active_sessions = sum(1 for q in user_queues.values() if q)
        response = JSONResponse(
            {
                "session_id": session_id,
                "current_job_id": current_job_id,
                "queue": queue_entries,
                "waiting_total": waiting_total,
                "active_sessions": active_sessions,
            }
        )
        if set_cookie:
            response.set_cookie(session_cookie, session_id, max_age=60 * 60 * 24 * 30)
        return response

    @app.get("/metrics/estimate")
    def get_metrics_estimate() -> Response:
        model = _fit_duration_model()
        return JSONResponse(model)

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
        filename = f"{job.image_name or 'scene'}.ply"
        headers = {"Content-Disposition": f"{disposition}; filename={filename}"}
        return Response(content=job.ply_bytes, media_type="application/octet-stream", headers=headers)

    @app.get("/jobs/{job_id}/ply/{filename}.ply")
    def get_ply_named(job_id: str, filename: str, download: int = 0):
        return get_ply(job_id, download=download)

    return app


# Convenience for `uvicorn sharp.web.app:app`
app = create_app()
