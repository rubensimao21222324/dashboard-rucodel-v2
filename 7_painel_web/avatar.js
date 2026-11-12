import * as THREE from 'three';
import { FBXLoader } from './vendor/three/examples/jsm/loaders/FBXLoader.js';

// The avatar is a locally packaged Microsoft Rocketbox character (MIT).
// Mouth movement follows the actual audio envelope; it is not phoneme alignment.
export class JarvisAvatar {
  constructor(container, onReady, onError) {
    this.container = container;
    this.ready = false;
    this.speech = null;
    this.openness = 0;
    this.morphMeshes = [];
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    try {
      this.renderer = new THREE.WebGLRenderer({antialias:true, alpha:true, powerPreference:'high-performance'});
      this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
      this.renderer.setClearColor(0x000000,0);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.05;
      container.appendChild(this.renderer.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(29,1,.01,100);
      this.scene.add(new THREE.HemisphereLight(0xfff7ef,0x39444a,1.8));
      const key = new THREE.DirectionalLight(0xfff1e2,3.2); key.position.set(2,3,4); this.scene.add(key);
      const fill = new THREE.DirectionalLight(0xd5e4ed,.8); fill.position.set(-3,2,1); this.scene.add(fill);
      const rim = new THREE.DirectionalLight(0x76b9c7,2.3); rim.position.set(-1,2,-3); this.scene.add(rim);
      this.resize = new ResizeObserver(()=>this.fit()); this.resize.observe(container);
      this.fit();
      this.nextBlink = performance.now()/1000 + 2.2;
      this.blinkStart = -100;
      this.prevTime = performance.now();
      this.renderer.setAnimationLoop(()=>this.animate());
      this.load().then(()=>onReady()).catch(onError);
    } catch (e) { onError(e); }
  }
  async load() {
    const manager = new THREE.LoadingManager();
    const textureLoader = new THREE.TextureLoader(manager);
    manager.addHandler(/\.tga$/i, textureLoader);
    manager.setURLModifier(url=>{
      if (!/\.tga$/i.test(url)) return url;
      const file = url.replaceAll('\\','/').split('/').pop().replace(/\.tga$/i,'.png');
      return ['m005_head_color.png','m005_body_color.png','m005_head_normal.png','m005_body_normal.png','m005_opacity_color.png'].includes(file) ? './assets/'+file : './assets/pixel.png';
    });
    const model = await new FBXLoader(manager).loadAsync('./assets/jarvis.fbx');
    const tex = {};
    const bitmapLoader=new THREE.ImageBitmapLoader(manager).setOptions({imageOrientation:'flipY',premultiplyAlpha:'none'});
    const loadTexture=async url=>{const bitmap=await bitmapLoader.loadAsync(url);const texture=new THREE.Texture(bitmap);texture.flipY=false;texture.needsUpdate=true;return texture;};
    for (const part of ['head','body','opacity']) {
      tex[part] = await loadTexture('./assets/m005_'+part+'_color.png');
      tex[part].colorSpace = THREE.SRGBColorSpace;
    }
    for (const part of ['head','body']) tex[part+'_normal'] = await loadTexture('./assets/m005_'+part+'_normal.png');
    const kept = ['AK_09_EyeBlinkLeft','AK_10_EyeBlinkRight','AK_25_JawOpen','AK_32_MouthFunnel','AK_38_MouthPucker','AK_44_MouthSmileLeft','AK_45_MouthSmileRight','AK_34_MouthLowerDownLeft','AK_35_MouthLowerDownRight'];
    this.bones = [];
    model.traverse(o=>{
      if (o.isBone) this.bones.push(o);
      if (!o.isMesh) return;
      const oldMats = Array.isArray(o.material)?o.material:[o.material];
      const mats = oldMats.map(old=>{
        const part = /head/.test(old.name.toLowerCase())?'head': /opacity|hair/.test(old.name.toLowerCase())?'opacity':'body';
        const mat = new THREE.MeshStandardMaterial({map:tex[part],color:part==='head'?0xffeddf:0xffffff,roughness:part==='head'?.86:.88,metalness:0,side:THREE.DoubleSide});
        if (part!=='opacity') {mat.normalMap=tex[part+'_normal'];mat.normalScale=new THREE.Vector2(part==='head'?.08:.3,part==='head'?-.08:-.3);}
        else {mat.transparent=true;mat.alphaTest=.35;mat.depthWrite=true;}
        mat.name=old.name;
        return mat;
      });
      o.material = Array.isArray(o.material)?mats:mats[0];
      o.frustumCulled=false;
      if (o.morphTargetDictionary) {
        const entries=Object.entries(o.morphTargetDictionary).filter(([name])=>kept.some(k=>name.endsWith(k)));
        const names=entries.map(([n])=>n);
        for(const attr of Object.keys(o.geometry.morphAttributes)) o.geometry.morphAttributes[attr]=entries.map(([,i])=>o.geometry.morphAttributes[attr][i]);
        o.geometry.morphAttributes.position?.forEach((a,i)=>a.name=names[i]);
        o.updateMorphTargets();
        this.morphMeshes.push(o);
      }
    });
    model.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(model);
    const size=bounds.getSize(new THREE.Vector3());
    const center=bounds.getCenter(new THREE.Vector3());
    const scale=1.8/size.y;
    model.scale.multiplyScalar(scale);
    model.position.set(-center.x*scale,-bounds.min.y*scale,-center.z*scale);
    this.model=model;
    this.scene.add(model);
    model.updateMatrixWorld(true);
    this.head = this.bones.find(b=>/^Bip01[_ ]Head$/i.test(b.name));
    this.neck = this.bones.find(b=>/^Bip01[_ ]Neck$/i.test(b.name));
    if(this.head) this.headRest=this.head.quaternion.clone();
    if(this.neck) this.neckRest=this.neck.quaternion.clone();
    this.relaxArms();
    this.ready=true;
    this.fit();
    window.__jarvisAvatar=this;
  }
  relaxArms() {
    for(const side of ['L','R']) {
      const arm=this.bones.find(b=>new RegExp('Bip01[_ ]'+side+'[_ ]UpperArm','i').test(b.name));
      const child=arm?.children.find(b=>b.isBone);
      if(!arm||!child) continue;
      const p=arm.getWorldPosition(new THREE.Vector3());
      const d=child.getWorldPosition(new THREE.Vector3()).sub(p).normalize();
      const target=new THREE.Vector3(p.x<0?-.18:.18,-1,.035).normalize();
      const q=new THREE.Quaternion().setFromUnitVectors(d,target);
      const desired=q.multiply(arm.getWorldQuaternion(new THREE.Quaternion()));
      const parentQ=arm.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
      arm.quaternion.copy(parentQ.multiply(desired));
      this.model.updateMatrixWorld(true);
    }
  }
  fit() {
    const w=this.container.clientWidth,h=this.container.clientHeight;
    if(!w||!h||!this.renderer) return;
    this.renderer.setSize(w,h,false);
    this.camera.aspect=w/h;
    this.camera.position.set(0,1.58,w/h<.8?2.3:1.9);
    this.camera.lookAt(0,1.34,0);
    this.camera.updateProjectionMatrix();
  }
  setMorph(suffix,value) {
    for(const mesh of this.morphMeshes) for(const [name,index] of Object.entries(mesh.morphTargetDictionary)) if(name.endsWith(suffix)) mesh.morphTargetInfluences[index]=value;
  }
  setSpeech(volumes,sliceLength,audioContext,startTime,duration) {this.speech={volumes,sliceLength,audioContext,startTime,duration};}
  stopSpeech() {this.speech=null;}
  setActive(active) {
    if (!this.renderer) return;
    this.prevTime=performance.now();
    this.renderer.setAnimationLoop(active?()=>this.animate():null);
  }
  dispose() {
    this.resize?.disconnect();
    this.renderer?.setAnimationLoop(null);
    this.scene?.traverse(o=>{if(o.isMesh){o.geometry?.dispose();for(const mat of Array.isArray(o.material)?o.material:[o.material])mat?.dispose();}});
    this.renderer?.dispose();
    this.renderer?.domElement.remove();
  }
  animate() {
    const now=performance.now(),t=now/1000,dt=Math.min((now-this.prevTime)/1000,.1);this.prevTime=now;
    if(this.ready) {
      let mouth=0;
      if(this.speech) {
        const elapsed=this.speech.audioContext.currentTime-this.speech.startTime;
        if(elapsed>=0&&elapsed<=this.speech.duration) mouth=this.speech.volumes[Math.floor(elapsed*1000/this.speech.sliceLength)]||0;
      }
      const target=Math.min(.65,Math.pow(mouth,1.15)*.65);
      this.openness=THREE.MathUtils.damp(this.openness,target,target>this.openness?30:20,dt);
      this.setMorph('AK_25_JawOpen',this.openness);
      this.setMorph('AK_32_MouthFunnel',this.openness*.07);
      this.setMorph('AK_34_MouthLowerDownLeft',this.openness*.08);
      this.setMorph('AK_35_MouthLowerDownRight',this.openness*.08);
      if(t>=this.nextBlink){this.blinkStart=t;this.nextBlink=t+2.6+Math.random()*3.4;}
      const bt=t-this.blinkStart;
      const blink=bt>=0&&bt<.21?Math.sin(bt/.21*Math.PI):0;
      this.setMorph('AK_09_EyeBlinkLeft',blink);
      this.setMorph('AK_10_EyeBlinkRight',blink);
      this.setMorph('AK_44_MouthSmileLeft',.04);
      this.setMorph('AK_45_MouthSmileRight',.04);
      if(!this.reduced) {
        const speaking=this.openness>.04;
        if(this.head) this.head.quaternion.copy(this.headRest).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.sin(t*.7)*.012,Math.sin(t*.38)*.018,Math.sin(t*.53)*.008+(speaking?Math.sin(t*2.3)*.008:0))));
        if(this.neck) this.neck.quaternion.copy(this.neckRest).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(0,Math.sin(t*.32)*.008,0)));
      }
    }
    this.renderer.render(this.scene,this.camera);
  }
}
