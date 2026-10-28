'use strict';
const $=id=>document.getElementById(id);
const state={yaw:0,pitch:0,fov:75,aspect:4/3,mode:'left',width:2400,filename:'scene.jpg',image:null};
let originalFile=null,heicBusy=false;
let backendAvailable=false;
let depthImage=null,depthEnabled=false,depthBusy=false,photoVersion=0;
const vertex=`attribute vec2 position; varying vec2 uv; void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`;
const fragment=`precision highp float;varying vec2 uv;uniform sampler2D photo,depth;uniform float depthOn;uniform float yaw,pitch,fov,aspect,mode;const float PI=3.141592653589793;
void main(){float u=uv.x;float eye=mode==1.?1.:0.;if(mode==2.){eye=step(.5,u);u=fract(u*2.);}float f=tan(fov*.5);vec3 r=vec3((u*2.-1.)*f,(1.-uv.y*2.)*f/aspect,1.);
 r=vec3(r.x,cos(pitch)*r.y+sin(pitch)*r.z,-sin(pitch)*r.y+cos(pitch)*r.z);
 r=vec3(cos(yaw)*r.x+sin(yaw)*r.z,r.y,-sin(yaw)*r.x+cos(yaw)*r.z);
 float lon=atan(r.x,r.z);float lat=atan(r.y,length(r.xz));
 if(r.z<=0.||abs(lon)>PI*.5){float c=mod(floor(gl_FragCoord.x/16.)+floor(gl_FragCoord.y/16.),2.);gl_FragColor=vec4(vec3(.08+c*.025),1.);return;}
 vec2 st=vec2((lon/PI+.5+eye)*.5,lat/PI+.5);vec3 rgb=texture2D(photo,st).rgb;if(depthOn>.5){vec4 d=texture2D(depth,vec2(lon/PI+.5,lat/PI+.5));float g=dot(rgb,vec3(.299,.587,.114));rgb=d.a>.5?mix(rgb,d.rgb,.8):vec3(g*.55);}gl_FragColor=vec4(rgb,1.);}`;

function renderer(canvas){
 const gl=canvas.getContext('webgl',{preserveDrawingBuffer:true,alpha:false});if(!gl)throw Error('浏览器不支持 WebGL，请使用新版 Edge 或 Chrome。');
 const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
 const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
 const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);const loc=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
 const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 const depthTexture=gl.createTexture();gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,depthTexture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array(4));gl.activeTexture(gl.TEXTURE0);
 let loaded=null,loadedDepth=null;
 return {draw(image,width,height,mode,overlay=false){if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}gl.viewport(0,0,width,height);gl.useProgram(program);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);if(image!==loaded){const limit=gl.getParameter(gl.MAX_TEXTURE_SIZE);let src=image;if(image.width>limit){src=document.createElement('canvas');src.width=limit;src.height=Math.round(image.height*limit/image.width);src.getContext('2d').drawImage(image,0,0,src.width,src.height);}gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,src);loaded=image;}
  gl.uniform1i(gl.getUniformLocation(program,'photo'),0);gl.uniform1i(gl.getUniformLocation(program,'depth'),1);gl.uniform1f(gl.getUniformLocation(program,'depthOn'),overlay&&depthEnabled&&depthImage?1:0);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,depthTexture);if(depthImage&&loadedDepth!==depthImage){gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,depthImage);loadedDepth=depthImage;}gl.activeTexture(gl.TEXTURE0);
  for(const [k,v] of Object.entries({yaw:state.yaw*Math.PI/180,pitch:state.pitch*Math.PI/180,fov:state.fov*Math.PI/180,aspect:state.aspect,mode:{left:0,right:1,sbs:2}[mode]}))gl.uniform1f(gl.getUniformLocation(program,k),v);gl.drawArrays(gl.TRIANGLES,0,6);},dispose(){gl.getExtension('WEBGL_lose_context')?.loseContext();}};
}
let preview;
try{preview=renderer($('view'));}catch(e){$('loading').textContent=e.message;}
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const degree=n=>`${n>0?'+':''}${Number(n.toFixed(1))}°`;
function rays(){const coords=[];const f=Math.tan(state.fov*Math.PI/360),a=state.pitch*Math.PI/180,b=state.yaw*Math.PI/180;for(let edge=0;edge<4;edge++)for(let i=0;i<=24;i++){const t=i/24;const [x,y]=edge===0?[-1+2*t,-1]:edge===1?[1,-1+2*t]:edge===2?[1-2*t,1]:[-1,1-2*t];let rx=x*f,ry=y*f/state.aspect,rz=1;[ry,rz]=[Math.cos(a)*ry+Math.sin(a)*rz,-Math.sin(a)*ry+Math.cos(a)*rz];[rx,rz]=[Math.cos(b)*rx+Math.sin(b)*rz,-Math.sin(b)*rx+Math.cos(b)*rz];coords.push([Math.atan2(rx,rz)/Math.PI+.5,Math.atan2(ry,Math.hypot(rx,rz))/Math.PI+.5,rz]);}return coords;}
function update(){
 for(const key of ['yaw','pitch','fov']){$(key).value=state[key];$(key+'Value').textContent=degree(state[key]);}
 const boundaries=rays();const valid=boundaries.every(p=>p[2]>0&&p[0]>=0&&p[0]<=1);
 $('summaryDirection').textContent=`${degree(state.yaw)} / ${degree(state.pitch)}`;$('summarySize').textContent=`${state.width} × ${Math.round(state.width/state.aspect)}`;
 $('viewStatus').textContent=`左右 ${degree(state.yaw)}　俯仰 ${degree(state.pitch)}　FOV ${state.fov}°`;
 $('boundaryStatus').textContent=valid?'视野位于有效区域':'超出 VR180 范围 · 请缩小视场或调整角度';$('boundaryStatus').classList.toggle('invalid',!valid);
 const supported=!!state.image&&valid&&state.yaw===0&&Number($('baseline').value)>0;
 $('compatibility').textContent=!valid?'部分画面超出原图覆盖范围，调整后再导出。':state.yaw!==0?'当前 HEIC 转换仅支持左右方向 0°；其他方向可导出 PNG。':supported?'可直接导出 HEIC；在本机完成几何校正与编码。':'请选择 LR 等距柱状 VR180 图片，并填写实际相机基线。';
 if(!backendAvailable)$('compatibility').textContent='在线版支持本地取景及 PNG 导出。深度伪色和 HEIC 编码需下载项目并运行 framing.cmd。';
 $('depthToggle').disabled=!backendAvailable||!state.image;
 $('compatibility').classList.toggle('unsupported',!supported);$('copyCommand').disabled=!supported;
 $('saveDepth').disabled=!depthImage||!valid;$('exportHeic').disabled=!backendAvailable||heicBusy||!state.image||!valid||state.yaw!==0||!Number($('baseline').value);$('saveFrame').disabled=!state.image||!valid;$('saveConfig').disabled=!state.image;
 $('gridLines').hidden=!$('grid').checked;$('crosshair').hidden=!$('grid').checked;
 $('eyeLabel').textContent=depthEnabled?'DEPTH · LEFT EYE':{left:'LEFT EYE',right:'RIGHT EYE',sbs:'LEFT / RIGHT'}[state.mode];
 if(state.image&&preview){const st=$('stage'),displayAspect=state.aspect*(state.mode==='sbs'?2:1);const pad=window.innerWidth<=680?28:48;const maxW=st.clientWidth-pad,maxH=st.clientHeight-66;const w=Math.max(1,Math.min(maxW,maxH*displayAspect)),h=w/displayAspect;$('viewport').style.width=w+'px';$('viewport').style.height=h+'px';const dpr=Math.min(window.devicePixelRatio||1,2);preview.draw(state.image,Math.round(w*dpr),Math.round(h*dpr),state.mode,true);
 const map=$('map'),ctx=map.getContext('2d');ctx.drawImage(state.image,0,0,state.image.width/2,state.image.height,0,0,map.width,map.height);ctx.fillStyle='#0007';ctx.fillRect(0,0,map.width,map.height);ctx.beginPath();boundaries.forEach((p,i)=>{const x=clamp(p[0],0,1)*map.width,y=p[1]*map.height;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fillStyle='#d7edaf28';ctx.fill();ctx.strokeStyle='#d7edaf';ctx.lineWidth=2;ctx.stroke();const x=(state.yaw/180+.5)*map.width,y=(state.pitch/180+.5)*map.height;ctx.fillStyle='#e6f8cb';ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fill();}
}
async function load(url,name){$('loading').hidden=false;$('loading').textContent='正在读取原图…';try{if(!preview)throw Error('浏览器不支持 WebGL，请使用新版 Edge 或 Chrome。');const image=new Image();image.src=url;await image.decode();if(image.width!==image.height*2)throw Error('请选择 2:1 全宽 SBS 图片，每眼应为 180° × 180° 等距柱状图。');photoVersion++;depthImage=null;depthEnabled=false;depthBusy=false;$('depthToggle').checked=false;$('depthToggle').disabled=false;$('depthLegend').hidden=true;$('depthStatus').textContent=backendAvailable?'根据双眼视差估计相对远近；首次开启需数秒。':'在线版不提供深度计算，请运行本地 Python 服务。';$('baseline').value='';state.image=image;state.filename=name;$('filename').textContent=name;$('sourceInfo').textContent=`${image.width} × ${image.height}　·　VR180 / SBS`;$('loading').hidden=true;update();}catch(e){$('loading').textContent=e.message;}finally{if(url.startsWith('blob:'))URL.revokeObjectURL(url);}}
for(const key of ['yaw','pitch','fov'])$(key).addEventListener('input',e=>{state[key]=Number(e.target.value);update();});
$('resolution').addEventListener('change',e=>{state.width=Number(e.target.value);update();});$('grid').addEventListener('change',update);
for(const b of document.querySelectorAll('#aspects button'))b.onclick=()=>{state.aspect=Number(b.dataset.aspect);document.querySelectorAll('#aspects button').forEach(x=>x.classList.toggle('active',x===b));update();};
for(const b of document.querySelectorAll('#modes button'))b.onclick=()=>{state.mode=b.dataset.mode;if(state.mode!=='left'){depthEnabled=false;$('depthToggle').checked=false;$('depthLegend').hidden=true;}document.querySelectorAll('#modes button').forEach(x=>x.classList.toggle('active',x===b));update();};
for(const b of document.querySelectorAll('.preset-list button'))b.onclick=()=>{for(const k of ['yaw','pitch','fov'])state[k]=Number(b.dataset[k]);update();};
$('reset').onclick=()=>{state.yaw=0;state.pitch=0;state.fov=75;update();};
$('open').onclick=()=>$('file').click();$('file').onchange=e=>{const file=e.target.files[0];if(file){originalFile=file;load(URL.createObjectURL(file),file.name);}};
let drag=null;$('stage').addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw:state.yaw,pitch:state.pitch};$('stage').setPointerCapture(e.pointerId);$('stage').classList.add('dragging');});$('stage').addEventListener('pointermove',e=>{if(!drag)return;const speed=state.fov/$('viewport').clientWidth;state.yaw=clamp(Math.round((drag.yaw-(e.clientX-drag.x)*speed)*2)/2,-85,85);state.pitch=clamp(Math.round((drag.pitch-(e.clientY-drag.y)*speed)*2)/2,-80,80);update();});function endDrag(){drag=null;$('stage').classList.remove('dragging');}for(const type of ['pointerup','pointercancel'])$('stage').addEventListener(type,endDrag);
$('stage').addEventListener('wheel',e=>{e.preventDefault();state.fov=clamp(Math.round((state.fov+e.deltaY*.03)*2)/2,30,88);update();},{passive:false});$('stage').addEventListener('keydown',e=>{const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!delta)return;e.preventDefault();state.yaw=clamp(state.yaw+delta[0],-85,85);state.pitch=clamp(state.pitch+delta[1],-80,80);update();});
$('map').onclick=e=>{const r=e.target.getBoundingClientRect();state.yaw=clamp(Math.round(((e.clientX-r.left)/r.width-.5)*180*2)/2,-85,85);state.pitch=clamp(Math.round(((e.clientY-r.top)/r.height-.5)*180*2)/2,-80,80);update();};
function download(blob,name){const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
function config(){return {schema:'vr180-frame-v1',source:state.filename,projection:'equirect180',eye_order:'lr',yaw_degrees_right:state.yaw,pitch_degrees_down:state.pitch,hfov:state.fov,width:state.width,height:Math.round(state.width/state.aspect),heic_cli_supported:state.yaw===0&&rays().every(p=>p[2]>0),preview_rectification:false};}
const stem=()=>state.filename.replace(/\.[^.]+$/,'')+`_yaw${state.yaw}_pitch${state.pitch}_fov${state.fov}`;
$('saveConfig').onclick=()=>{download(new Blob([JSON.stringify(config(),null,2)],{type:'application/json'}),stem()+'.frame.json');$('toast').textContent='取景参数已保存。';};
$('saveFrame').onclick=()=>{const button=$('saveFrame');button.disabled=true;$('toast').textContent='正在生成全分辨率双眼取景图…';setTimeout(()=>{let r;try{const c=document.createElement('canvas');r=renderer(c);r.draw(state.image,state.width*2,Math.round(state.width/state.aspect),'sbs');c.toBlob(blob=>{if(blob){download(blob,stem()+'.sbs.png');$('toast').textContent='双眼取景图已保存。';}else $('toast').textContent='导出失败，请降低输出宽度。';r.dispose();update();},'image/png');}catch(e){$('toast').textContent=e.message;r?.dispose();update();}},30);};
$('copyCommand').onclick=async()=>{const c=config();const command=`.\\.venv\\Scripts\\python.exe vr180_to_spatial.py '${state.filename.replaceAll("'","''")}' --projection equirect180 --baseline-mm ${Number($('baseline').value)} --pitch ${c.pitch_degrees_down} --hfov ${c.hfov} --width ${c.width} --height ${c.height} --output-dir 'output/web_${Date.now()}' --save-eyes`;try{await navigator.clipboard.writeText(command);$('toast').textContent='转换命令已复制，在项目目录的 PowerShell 中粘贴运行。';}catch{$('toast').textContent=command;}};
new ResizeObserver(update).observe($('stage'));
update();
$('loading').textContent='点击右上角「打开照片」，选择 2:1 左右并排 VR180 图片。';
$('depthStatus').textContent='在线版不提供深度计算，请运行本地 Python 服务。';
if(['127.0.0.1','localhost'].includes(location.hostname)){
 fetch('api/capabilities').then(r=>r.ok?r.json():null).then(data=>{
  backendAvailable=data?.spatial_export===true;
  $('depthStatus').textContent=backendAvailable?'根据双眼视差估计相对远近；首次开启需数秒。':'未连接本地 Python 服务。';update();
 }).catch(()=>{});
}

$('depthToggle').addEventListener('change',async()=>{
 if(!backendAvailable)return;
 depthEnabled=$('depthToggle').checked;
 $('depthLegend').hidden=!depthEnabled;
 if(!depthEnabled){update();return;}
 state.mode='left';document.querySelectorAll('#modes button').forEach(b=>b.classList.toggle('active',b.dataset.mode==='left'));update();
 if(depthImage||depthBusy)return;
 if(!state.image){$('depthToggle').checked=false;depthEnabled=false;return;}
 const version=photoVersion;depthBusy=true;$('depthStatus').textContent='正在本机计算双眼视差…';
 try{
  const c=document.createElement('canvas');c.width=1536;c.height=768;c.getContext('2d').drawImage(state.image,0,0,c.width,c.height);
  const blob=await new Promise(resolve=>c.toBlob(resolve,'image/png'));
  const response=await fetch('api/depth',{method:'POST',headers:{'Content-Type':'image/png'},body:blob});
  if(!response.ok){let message='深度计算失败，请确认本地服务已更新。';try{message=(await response.json()).error||message;}catch{}throw Error(message);}
  const result=await response.json();const img=new Image();img.src=result.image;await img.decode();
  if(version!==photoVersion)return;
  depthImage=img;$('depthStatus').textContent=`全图可靠覆盖 ${result.valid_percent}% · 灰色为无可靠匹配；色标固定于整张照片。`;
 }catch(e){if(version===photoVersion){depthEnabled=false;$('depthToggle').checked=false;$('depthLegend').hidden=true;$('depthStatus').textContent=e.message;}}
 finally{if(version===photoVersion){depthBusy=false;update();}}
});

$('baseline').addEventListener('input',update);
$('saveDepth').onclick=()=>{
 if(!depthImage)return;
 const c=document.createElement('canvas'),r=renderer(c),wasEnabled=depthEnabled;
 try{depthEnabled=true;r.draw(state.image,state.width,Math.round(state.width/state.aspect),'left',true);
 c.toBlob(blob=>{if(blob)download(blob,stem()+'.depth.png');r.dispose();},'image/png');}
 finally{depthEnabled=wasEnabled;}
};
$('exportHeic').onclick=async()=>{
 if(heicBusy||!backendAvailable)return;
 heicBusy=true;update();
 const params={yaw:state.yaw,pitch:state.pitch,hfov:state.fov,width:state.width,height:Math.round(state.width/state.aspect),baseline:Number($('baseline').value)};
 const name=stem()+'.spatial.heic',file=originalFile;
 $('exportStatus').textContent='正在本机校正与编码，请稍候；完成后自动下载…';
 try{
  const source=file;
  if(!source)throw Error('请重新打开原图');
  const response=await fetch('api/export-spatial',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-VR180-Frame':JSON.stringify(params)},body:source});
  if(!response.ok){let message='导出失败，请检查取景参数或稍后重试。';try{message=(await response.json()).error||message;}catch{}throw Error(message);}
  download(await response.blob(),name);$('exportStatus').textContent='空间 HEIC 已生成并下载。校正可能裁去边缘，请在 Vision Pro 检查观看效果。';
 }catch(e){$('exportStatus').textContent=e.message;}
 finally{heicBusy=false;update();}
};
