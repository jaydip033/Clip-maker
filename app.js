const fileInput=document.getElementById('videoFile');
const dropzone=document.getElementById('dropzone');
const generateBtn=document.getElementById('generateBtn');
const fileInfo=document.getElementById('fileInfo');
const emptyState=document.getElementById('emptyState');
const progressState=document.getElementById('progressState');
const errorState=document.getElementById('errorState');
const clipsList=document.getElementById('clipsList');
const clipCount=document.getElementById('clipCount');
let selectedFile=null, polling=null;

function fmtSize(bytes){if(bytes<1024*1024)return `${(bytes/1024).toFixed(0)} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`;}
function chooseFile(file){
  if(!file)return;
  const allowed=['.mp4','.mov','.mkv','.webm','.m4v'];
  if(!allowed.some(ext=>file.name.toLowerCase().endsWith(ext))){showError('Unsupported file type. Choose MP4, MOV, MKV, WebM, or M4V.');return;}
  selectedFile=file;fileInfo.textContent=`Selected: ${file.name} · ${fmtSize(file.size)}`;fileInfo.classList.remove('hidden');generateBtn.disabled=false;errorState.classList.add('hidden');
}
fileInput.addEventListener('change',e=>chooseFile(e.target.files[0]));
['dragenter','dragover'].forEach(ev=>dropzone.addEventListener(ev,e=>{e.preventDefault();dropzone.classList.add('dragging')}));
['dragleave','drop'].forEach(ev=>dropzone.addEventListener(ev,e=>{e.preventDefault();dropzone.classList.remove('dragging')}));
dropzone.addEventListener('drop',e=>chooseFile(e.dataTransfer.files[0]));
function showError(message){errorState.textContent=message;errorState.classList.remove('hidden');progressState.classList.add('hidden');}
function showProgress(){emptyState.classList.add('hidden');progressState.classList.remove('hidden');errorState.classList.add('hidden');clipsList.innerHTML='';clipCount.textContent='Processing';}
function setProgress(job){document.getElementById('progressTitle').textContent=job.status==='rendering'?'Rendering your clips…':job.status==='transcribing'?'Listening to your video…':job.status==='selecting'?'Finding standout moments…':'Preparing your video…';document.getElementById('progressMessage').textContent=job.message||'Please keep this tab open.';document.getElementById('progressBar').style.width=(job.progress||0)+'%';document.getElementById('progressPercent').textContent=(job.progress||0)+'%';}
function renderClips(clips){
  clipsList.innerHTML='';clipCount.textContent=`${clips.length} clip${clips.length===1?'':'s'} ready`;
  clips.forEach((clip,i)=>{
    const card=document.createElement('article');card.className='clip-card';
    const thumb=document.createElement('div');thumb.className='clip-thumb';thumb.textContent='▶';
    const meta=document.createElement('div');meta.className='clip-meta';
    const title=document.createElement('h3');title.textContent=`Highlight ${String(i+1).padStart(2,'0')}`;
    const time=document.createElement('div');time.className='clip-time';time.textContent=`${clip.duration}s · ${clip.start}s – ${clip.end}s`;
    const desc=document.createElement('p');desc.textContent=clip.text||'AI-selected moment from your video.';
    const link=document.createElement('a');link.className='download';link.href=clip.download_url;link.textContent='↓ Download MP4';link.download=clip.filename;
    meta.append(title,time,desc,link);card.append(thumb,meta);clipsList.append(card);
  });
}
async function pollJob(id){
  try{
    const res=await fetch(`/api/jobs/${id}`);if(!res.ok)throw new Error('Could not read processing status.');const job=await res.json();setProgress(job);
    if(job.status==='completed'){clearInterval(polling);progressState.classList.add('hidden');renderClips(job.clips||[]);return;}
    if(job.status==='failed'){clearInterval(polling);showError(job.error||'Processing failed. Check that FFmpeg is installed and the server has enough memory.');return;}
  }catch(err){clearInterval(polling);showError(err.message);}
}
generateBtn.addEventListener('click',async()=>{
  if(!selectedFile)return;
  showProgress();generateBtn.disabled=true;generateBtn.textContent='Uploading video…';
  try{
    const form=new FormData();form.append('file',selectedFile);
    const res=await fetch('/api/upload',{method:'POST',body:form});
    const data=await res.json();if(!res.ok)throw new Error(data.detail||'Upload failed.');
    generateBtn.innerHTML='<span>✦</span> Generate AI clips <span class="arrow">→</span>';generateBtn.disabled=false;
    await pollJob(data.id);polling=setInterval(()=>pollJob(data.id),2500);
  }catch(err){showError(err.message);generateBtn.disabled=false;generateBtn.innerHTML='<span>✦</span> Try again <span class="arrow">→</span>';}
});
fetch('/api/health').then(r=>r.json()).then(h=>{if(!h.ffmpeg||!h.ffprobe)showError('Server setup warning: FFmpeg/FFprobe not detected. Install FFmpeg and restart the backend.');}).catch(()=>{});
