/* Semantic atlas: supplied coordinates, inspectable sources, presentation only. */
(function(root,factory){
  'use strict';
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.SemanticAtlas=api;
}(typeof window!=='undefined'?window:this,function(){
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const list=v=>Array.isArray(v)?v:[];
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short=(v,n=52)=>String(v||'').length>n?String(v).slice(0,n-1)+'…':String(v||'');
  const palette=['#57d3c3','#719ef4','#c18bf6','#e9b66d','#f088a9','#75c59a','#76bddc','#b1b7d5'];
  const color=v=>typeof v==='string'&&/^#[0-9a-f]{6}$/i.test(v)?v:null;
  const kind=p=>p.kind==='news_observation'||p.kind==='feedback_hypothesis'?p.kind:'guideline';
  function normalizePoints(values){
    const keys=new Set();
    return list(values).filter(p=>p&&finite(p.x)&&finite(p.y)&&p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1)
      .filter(p=>{const key=String(p.key??p.id??'');if(!key||keys.has(key))return false;keys.add(key);return true;})
      .map(p=>({...p,key:String(p.key??p.id),id:String(p.id??p.key),kind:kind(p),
        family_id:String(p.family_id||p.theme_id||p.cluster_id||'general'),title:String(p.title||p.label||p.id||'Recorded point')}));
  }
  function groupClusters(points,taxonomy=[]){
    const source=normalizePoints(points),catalog=new Map(list(taxonomy?.families||taxonomy).map(t=>[String(t.id),t]));
    const grouped=new Map();
    for(const p of source){if(!grouped.has(p.family_id))grouped.set(p.family_id,[]);grouped.get(p.family_id).push(p);}
    return [...grouped.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([id,items],i)=>{
      const meta=catalog.get(id)||{},mean={x:items.reduce((s,p)=>s+p.x,0)/items.length,y:items.reduce((s,p)=>s+p.y,0)/items.length};
      // Place a label at an observed local density peak, rather than an empty
      // mean between two disconnected islands. No source point moves.
      const density=p=>items.reduce((s,q)=>s+Math.exp(-((p.x-q.x)**2+(p.y-q.y)**2)/.009),0);
      const peak=items.reduce((best,p)=>density(p)>density(best)?p:best,items[0]);
      return {id,label:String(meta.label||items[0].family_label||items[0].theme_label||id.replaceAll('_',' ')),
        color:color(meta.color)||color(items[0].color)||palette[i%palette.length],count:items.length,
        guideline_count:items.filter(p=>p.kind==='guideline').length,observation_count:items.filter(p=>p.kind!=='guideline').length,
        x:peak.x,y:peak.y,mean,point_keys:items.map(p=>p.key),points:items};
    });
  }
  function nearestNeighbors(point,points,limit=5){
    if(!point||!finite(point.x)||!finite(point.y))return [];
    return normalizePoints(points).filter(p=>p.key!==point.key)
      .map(p=>({...p,map_distance:Math.hypot(p.x-point.x,p.y-point.y)}))
      .sort((a,b)=>a.map_distance-b.map_distance||a.key.localeCompare(b.key)).slice(0,Math.max(0,Math.min(12,limit)));
  }
  function pointPriority(point){
    if(point.lifecycle==='historical')return 0;
    if(point.lifecycle==='retired')return 1;
    return point.kind==='guideline'?3:2;
  }
  function pointPaintOrder(points,selectedKey=null){
    return normalizePoints(points).map((point,index)=>({point,index}))
      .sort((a,b)=>(a.point.key===selectedKey?10:pointPriority(a.point))-(b.point.key===selectedKey?10:pointPriority(b.point))||a.index-b.index)
      .map(row=>row.point);
  }
  function nearestPointerPoint(points,position,camera,width,height){
    if(!position||!finite(position.x)||!finite(position.y))return null;
    const c=camera||{x:0,y:0,k:1};
    return normalizePoints(points).map(point=>({point,distance:Math.hypot(point.x*width*c.k+c.x-position.x,point.y*height*c.k+c.y-position.y)}))
      .sort((a,b)=>Math.abs(a.distance-b.distance)<.75?pointPriority(b.point)-pointPriority(a.point)||a.distance-b.distance||a.point.key.localeCompare(b.point.key):a.distance-b.distance)[0]?.point||null;
  }
  function cameraForBounds(points,width,height,padding=70){
    const source=normalizePoints(points),w=Math.max(1,width),h=Math.max(1,height);
    if(!source.length)return {x:0,y:0,k:1};
    const xs=source.map(p=>p.x*w),ys=source.map(p=>p.y*h);
    const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
    const k=clamp(Math.min((w-padding*2)/Math.max(w*.24,maxX-minX),(h-padding*2)/Math.max(h*.24,maxY-minY)),.55,4);
    return {x:w/2-(minX+maxX)/2*k,y:h/2-(minY+maxY)/2*k,k};
  }
  function cameraForFamily(id,points,width,height,padding=82){
    const members=normalizePoints(points).filter(p=>p.family_id===String(id));
    return members.length?cameraForBounds(members,width,height,padding):null;
  }
  function labelLayout(clusters,width,height,avoidPoints=[]){
    const placed=[],out=[];
    const maximum=width<560?7:width<1000?11:12;
    const importance=c=>['market_geopolitics','market_energy'].includes(c.family_id||c.id)?100000+(c.count||0):(c.count||0)>=12?1000+(c.count||0):(c.count||0);
    const source=list(clusters).filter(c=>list(clusters).length<=maximum||(c.family_id||c.id)!=='market_other')
      .slice().sort((a,b)=>importance(b)-importance(a)||String(a.id).localeCompare(String(b.id))).slice(0,maximum);
    for(const cluster of source){
      // Italic 19px region titles need considerably more space than 11px UI
      // labels. Reserve the map's header and navigation area completely.
      const w=clamp(String(cluster.label||'').length*9.7+34,155,270),h=47;
      const px=cluster.x*width,py=cluster.y*height;
      const candidates=[[-w/2,-65],[22,-24],[-w-22,-24],[-w/2,30]];
      for(const radius of [85,130,185])for(let angle=0;angle<12;angle++){
        const a=angle*Math.PI/6;candidates.push([Math.cos(a)*radius-w/2,Math.sin(a)*radius-h/2]);
      }
      let best=null,bestScore=Infinity;
      for(const [dx,dy]of candidates){
        const box={x:clamp(px+dx,14,width-w-14),y:clamp(py+dy,130,height-h-82),w,h};
        let overlap=0;
        for(const prev of placed){const a=Math.max(0,Math.min(box.x+w,prev.x+prev.w)-Math.max(box.x,prev.x));const b=Math.max(0,Math.min(box.y+h,prev.y+prev.h)-Math.max(box.y,prev.y));overlap+=a*b;}
        let occlusion=0;
        for(const p of list(avoidPoints))if(p.x>box.x-5&&p.x<box.x+w+5&&p.y>box.y-5&&p.y<box.y+h+5)occlusion+=p.weight||25;
        const score=overlap*30+occlusion+Math.hypot(box.x+w/2-px,box.y+h/2-py);
        if(score<bestScore){best=box;bestScore=score;}
      }
      placed.push(best);out.push({...cluster,...best,anchorX:px,anchorY:py});
    }
    return out;
  }
  function contourPaths(points,{columns=42,rows=30,bandwidth=.065,levels=[.22,.40,.62,.82]}={}){
    const values=normalizePoints(points);if(!values.length)return [];
    const field=new Float64Array((columns+1)*(rows+1));
    let maximum=0;
    for(let y=0;y<=rows;y++)for(let x=0;x<=columns;x++){
      let density=0;
      for(const p of values){const d=(p.x-x/columns)**2+(p.y-y/rows)**2;if(d<bandwidth*bandwidth*20)density+=Math.exp(-d/(2*bandwidth*bandwidth));}
      field[y*(columns+1)+x]=density;maximum=Math.max(maximum,density);
    }
    if(!maximum)return [];
    const interpolate=(a,b,va,vb,t)=>{const f=va===vb?.5:clamp((t-va)/(vb-va),0,1);return [a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];};
    // Marching squares over a Gaussian density estimate of actual coordinates.
    // Disconnected semantic regions remain disconnected; no taxonomy hull is
    // stretched between unrelated points.
    return levels.map(fraction=>{
      const threshold=maximum*fraction,segments=[];
      for(let y=0;y<rows;y++)for(let x=0;x<columns;x++){
        const vertices=[[x/columns,y/rows],[(x+1)/columns,y/rows],[(x+1)/columns,(y+1)/rows],[x/columns,(y+1)/rows]];
        const v=[field[y*(columns+1)+x],field[y*(columns+1)+x+1],field[(y+1)*(columns+1)+x+1],field[(y+1)*(columns+1)+x]];
        const crossings=[];
        for(let edge=0;edge<4;edge++){const next=(edge+1)%4;if((v[edge]>=threshold)!==(v[next]>=threshold))crossings.push(interpolate(vertices[edge],vertices[next],v[edge],v[next],threshold));}
        if(crossings.length===2)segments.push([crossings[0],crossings[1]]);
        else if(crossings.length===4){segments.push([crossings[0],crossings[1]],[crossings[2],crossings[3]]);}
      }
      const key=p=>p.map(v=>v.toFixed(6)).join(':'),ends=new Map();
      segments.forEach((segment,index)=>segment.forEach(p=>{const k=key(p);if(!ends.has(k))ends.set(k,[]);ends.get(k).push(index);}));
      const seen=new Set(),paths=[];
      for(let i=0;i<segments.length;i++){
        if(seen.has(i))continue;seen.add(i);const chain=segments[i].map(p=>p.slice());
        for(const prepend of [false,true]){
          let p=prepend?chain[0]:chain[chain.length-1];
          for(let guard=0;guard<segments.length;guard++){
            const next=(ends.get(key(p))||[]).find(index=>!seen.has(index));if(next===undefined)break;
            seen.add(next);const s=segments[next],other=key(s[0])===key(p)?s[1]:s[0];
            if(prepend)chain.unshift(other);else chain.push(other);p=other;
          }
        }
        if(chain.length>2)paths.push(chain);
      }
      return {level:fraction,paths};
    });
  }
  function mount(element,options={}){
    if(!element||typeof document==='undefined')return null;
    const doc=element.ownerDocument||document,win=doc.defaultView||window;
    const reduced=Boolean(win.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    const uid='sa-'+Math.random().toString(36).slice(2,10);
    const state={points:[],references:[],clusters:[],families:[],selected:null,selectedTheme:'',camera:{x:0,y:0,k:1},width:1000,height:Number(options.height)||680,version:null,payload:{},destroyed:false,hovered:null,hasData:false};
    const create=(name,attrs={},text)=>{const n=doc.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
    element.classList.add('semantic-atlas');element.style.setProperty('--atlas-height',state.height+'px');
    element.innerHTML=`<div class="sa-topline"><div class="sa-overview"><span class="sa-kicker">SEMANTIC LANDSCAPE</span><h3>Ideas find their place.</h3><p class="sa-meta"></p></div><div class="sa-controls" aria-label="Map navigation"><button type="button" data-sa-action="zoom-in" aria-label="Zoom into semantic map">＋</button><button type="button" data-sa-action="zoom-out" aria-label="Zoom out of semantic map">−</button><button type="button" data-sa-action="fit" aria-label="Fit semantic map">↗<span>Fit map</span></button></div></div><div class="sa-stage"></div><div class="sa-tooltip" role="status" hidden></div><div class="sa-bottomline"><div class="sa-shape-key"><span><i class="rule"></i>Guidelines</span><span><i class="news"></i>News</span><span><i class="research"></i>Research</span></div><span class="sa-method"></span><span class="sa-gesture">Scroll to zoom · drag to explore</span></div><div class="sa-families" role="group" aria-label="Atlas theme families"></div>`;
    const stage=element.querySelector('.sa-stage'),tooltip=element.querySelector('.sa-tooltip'),familyDock=element.querySelector('.sa-families');
    const svg=create('svg',{class:'sa-svg',role:'group','aria-label':'Interactive semantic landscape. Arrow keys explore points; plus and minus zoom; zero fits the map.',tabindex:0});
    const defs=create('defs');
    const glow=create('filter',{id:uid+'-glow',x:'-100%',y:'-100%',width:'300%',height:'300%'});glow.append(create('feGaussianBlur',{stdDeviation:5}));defs.append(glow);
    const blur=create('filter',{id:uid+'-mist',x:'-30%',y:'-30%',width:'160%',height:'160%'});blur.append(create('feGaussianBlur',{stdDeviation:14}));defs.append(blur);
    const marker=create('marker',{id:uid+'-arrow',viewBox:'0 0 8 8',refX:7,refY:4,markerWidth:5,markerHeight:5,orient:'auto'});marker.append(create('path',{d:'M0 1 L7 4 L0 7',fill:'none',stroke:'#e7c78e','stroke-width':1}));defs.append(marker);svg.append(defs);
    const base=create('rect',{class:'sa-base',x:0,y:0,width:'100%',height:'100%'});svg.append(base);
    const scene=create('g',{class:'sa-scene'}),contours=create('g',{class:'sa-contours','aria-hidden':'true'}),trails=create('g',{class:'sa-trajectories','aria-hidden':'true'}),links=create('g',{class:'sa-neighbors','aria-hidden':'true'}),nodes=create('g',{class:'sa-nodes'}),labels=create('g',{class:'sa-cluster-labels'});
    scene.append(contours,trails,links,nodes);svg.append(scene,labels);stage.append(svg);
    const nodeElements=new Map(),pointByKey=()=>new Map(state.points.map(p=>[p.key,p]));
    let lastReferenceKey='',lastClustersKey='',oldById=new Map(),pointer=null,moved=false,frame=null,resizeObserver=null;
    const project=p=>({x:p.x*state.width,y:p.y*state.height});
    const screen=p=>{const a=project(p),c=state.camera;return {x:a.x*c.k+c.x,y:a.y*c.k+c.y};};
    const hideTooltip=()=>{tooltip.hidden=true;nodeElements.get(state.hovered)?.classList.remove('is-hovered');state.hovered=null;};
    const pointerPoint=e=>nearestPointerPoint(state.points,position(e),state.camera,state.width,state.height);
    function showTooltip(p,event){
      state.hovered=p.key;const family=state.families.find(c=>c.id===p.family_id),label=p.kind==='guideline'?'Policy guideline':p.kind==='feedback_hypothesis'?'Research hypothesis':'Saved news observation';
      tooltip.innerHTML=`<span class="sa-tooltip-type" style="color:${color(p.color)||family?.color||'#9bbbd0'}">${esc(label)}</span><strong>${esc(short(p.title,94))}</strong><small>${esc(family?.label||p.family_label||p.family_id)}${p.lifecycle&&p.kind==='guideline'?' · '+esc(p.lifecycle):''}</small>${p.source_agent?`<small>${esc(p.source_agent)}</small>`:''}`;
      tooltip.hidden=false;
      const rect=element.getBoundingClientRect(),at=event?.clientX!==undefined?{x:event.clientX-rect.left,y:event.clientY-rect.top}:screen(p);
      tooltip.style.left=clamp(at.x+18,12,Math.max(12,rect.width-300))+'px';tooltip.style.top=clamp(at.y-28,84,state.height-120)+'px';
    }
    function redrawLabels(){
      labels.replaceChildren();
      const visible=new Set(state.points.map(p=>p.key));
      const candidates=state.clusters.filter(c=>list(c.point_keys).some(k=>visible.has(k))).map(c=>{const s=screen(c);return {...c,x:s.x/state.width,y:s.y/state.height};}).filter(c=>c.x>-.05&&c.x<1.05&&c.y>.06&&c.y<.94);
      const avoid=state.points.map(p=>({...screen(p),weight:p.kind==='guideline'&&!['historical','retired'].includes(p.lifecycle)?180:p.lifecycle==='historical'?4:20}));
      for(const label of labelLayout(candidates,state.width,state.height,avoid)){
        const familyId=label.family_id||label.id,muted=state.selectedTheme&&state.selectedTheme!==familyId;
        const g=create('g',{class:'sa-cluster-label'+(muted?' is-muted':''),transform:`translate(${label.x},${label.y})`,role:'button',tabindex:0,'aria-label':`Explore ${label.label}`,'data-family':label.id});
        g.style.setProperty('--cluster-color',label.color);
        g.append(create('line',{x1:label.w/2,y1:label.h/2,x2:label.anchorX-label.x,y2:label.anchorY-label.y,class:'sa-label-leader'}));
        g.append(create('rect',{width:label.w,height:label.h,rx:9,class:'sa-label-panel'}));
        g.append(create('circle',{cx:10,cy:15,r:2.1,fill:label.color}));
        g.append(create('text',{x:20,y:22,class:'sa-cluster-title'},short(label.label,30)));
        g.append(create('text',{x:20,y:37,class:'sa-cluster-count'},`${label.count??0} texts · ${label.observation_count??0} sources`));
        const activate=()=>options.onThemeSelect?.(state.selectedTheme===familyId?'':familyId);
        g.addEventListener('click',e=>{e.stopPropagation();activate();});g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();activate();}});labels.append(g);
      }
    }
    function applyCamera(animate=false){
      scene.classList.toggle('is-moving',animate&&!reduced);const c=state.camera;scene.setAttribute('transform',`translate(${c.x},${c.y}) scale(${c.k})`);
      element.querySelector('[data-sa-action="zoom-in"]').disabled=c.k>=7.99;element.querySelector('[data-sa-action="zoom-out"]').disabled=c.k<=.56;
      // Point radii and stroke remain legible without growing into large blobs.
      scene.style.setProperty('--inverse-zoom',String(1/Math.sqrt(c.k)));redrawLabels();options.onCameraChange?.({...c});
    }
    function zoomBy(factor,at={x:state.width/2,y:state.height/2}){
      if(!finite(factor)||factor<=0)return;hideTooltip();const c=state.camera,next=clamp(c.k*factor,.55,8),ratio=next/c.k;
      state.camera={x:at.x-(at.x-c.x)*ratio,y:at.y-(at.y-c.y)*ratio,k:next};applyCamera(true);
    }
    function fit(){state.camera=cameraForBounds(state.references.length?state.references:state.points,state.width,state.height,82);hideTooltip();applyCamera(true);}
    function focusFamily(id){
      const camera=cameraForFamily(id,state.references.length?state.references:state.points,state.width,state.height);
      if(!camera)return false;state.camera=camera;hideTooltip();applyCamera(true);return true;
    }
    // Only an explicit UI reset clears the host's family filter. The public
    // camera methods never emit a theme callback, avoiding render/fit recursion.
    function resetView(){if(state.selectedTheme)options.onThemeSelect?.('');fit();}
    function focus(key){const p=pointByKey().get(String(key));if(!p)return;const k=Math.max(1.8,state.camera.k),a=project(p);state.camera={x:state.width*.48-a.x*k,y:state.height*.51-a.y*k,k};applyCamera(true);}
    function drawNeighbors(){
      links.replaceChildren();const selected=pointByKey().get(state.selected);if(!selected)return;
      let neighbors=list(selected.neighbor_keys).map(k=>pointByKey().get(k)).filter(Boolean).slice(0,5);
      if(!neighbors.length&&list(selected.neighbors).length)neighbors=selected.neighbors.map(item=>pointByKey().get(typeof item==='string'?item:item.key)).filter(Boolean).slice(0,5);
      if(!neighbors.length)neighbors=nearestNeighbors(selected,state.points,5).filter(p=>p.map_distance<.30);
      const a=project(selected),family=state.families.find(c=>c.id===selected.family_id);
      for(const [i,p]of neighbors.entries()){
        const b=project(p),dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,bend=Math.min(36,len*.12)*(i%2?1:-1),cx=(a.x+b.x)/2-dy/len*bend,cy=(a.y+b.y)/2+dx/len*bend;
        links.append(create('path',{d:`M${a.x} ${a.y} Q${cx} ${cy} ${b.x} ${b.y}`,stroke:family?.color||'#7ca3bd',class:'sa-neighbor-link'}));
      }
    }
    function drawTrails(){
      trails.replaceChildren();const byKey=pointByKey(),selected=byKey.get(state.selected),all=list(state.payload.trajectories).slice(0,80);
      let shown=0;
      for(const t of all){
        const a=typeof t.from==='string'?byKey.get(t.from):t.from,b=typeof t.to==='string'?byKey.get(t.to):t.to;
        if(!a||!b||!finite(a.x)||!finite(a.y)||!finite(b.x)||!finite(b.y))continue;
        const active=selected&&(selected.id===t.id||selected.key===a.key||selected.key===b.key);
        if(selected&&!active||!selected&&shown>=6)continue;shown++;
        const p=project(a),q=project(b),dx=q.x-p.x,dy=q.y-p.y,len=Math.hypot(dx,dy)||1;
        const path=create('path',{class:'sa-revision-trail'+(active?' is-active':''),d:`M${p.x} ${p.y} Q${(p.x+q.x)/2-dy/len*18} ${(p.y+q.y)/2+dx/len*18} ${q.x} ${q.y}`,'marker-end':`url(#${uid}-arrow)`});
        trails.append(path,create('circle',{cx:p.x,cy:p.y,r:3,class:'sa-trail-origin'}));
      }
    }
    function setSelected(key,notify=true){
      state.selected=key===null?null:String(key);hideTooltip();
      for(const [k,node]of nodeElements){node.classList.toggle('is-selected',k===state.selected);node.setAttribute('aria-pressed',String(k===state.selected));node.setAttribute('tabindex',k===state.selected||!state.selected&&k===state.points[0]?.key?'0':'-1');}
      stackPoints();
      drawNeighbors();drawTrails();if(notify)options.onSelect?.(state.selected?pointByKey().get(state.selected)||null:null);
    }
    function stackPoints(){
      for(const p of pointPaintOrder(state.points,state.selected)){const node=nodeElements.get(p.key);if(node)nodes.append(node);}
    }
    function drawContours(){
      contours.replaceChildren();
      for(const cluster of state.clusters){
        const rows=list(cluster.points).length?cluster.points:state.references.filter(p=>list(cluster.point_keys).includes(p.key));
        if(!rows.length)continue;
        const familyId=cluster.family_id||cluster.id;
        const group=create('g',{'data-family':familyId,class:'sa-density'+(state.selectedTheme&&state.selectedTheme!==familyId?' is-muted':'')});
        for(const level of contourPaths(rows))for(const path of level.paths){
          const d=path.map((p,i)=>`${i?'L':'M'}${(p[0]*state.width).toFixed(2)} ${(p[1]*state.height).toFixed(2)}`).join(' ')+' Z';
          if(level.level<.3)group.append(create('path',{d,fill:cluster.color,opacity:.10,filter:`url(#${uid}-mist)`,class:'sa-density-mist'}));
          group.append(create('path',{d,fill:cluster.color,'fill-opacity':.018+level.level*.024,stroke:cluster.color,'stroke-opacity':.10+level.level*.11,'stroke-width':level.level>.6?.65:.85,'vector-effect':'non-scaling-stroke',class:'sa-contour-line'}));
        }
        contours.append(group);
      }
    }
    function drawPoints(){
      nodes.querySelectorAll('.sa-empty-label').forEach(n=>n.remove());
      const wanted=new Set(state.points.map(p=>p.key)),families=new Map(state.families.map(c=>[c.id,c]));
      for(const [key,node]of nodeElements)if(!wanted.has(key)){node.remove();nodeElements.delete(key);}
      for(const p of state.points){
        let node=nodeElements.get(p.key),fresh=!node;const fill=color(p.color)||families.get(p.family_id)?.color||'#96b4c9';
        if(fresh){
          node=create('g',{role:'button','data-atlas-key':p.key});nodeElements.set(p.key,node);nodes.append(node);
          const datum=()=>pointByKey().get(p.key);
          node.addEventListener('click',e=>{e.stopPropagation();if(!moved)setSelected(e.detail===0?p.key:pointerPoint(e)?.key||p.key);});
          node.addEventListener('dblclick',e=>{e.stopPropagation();focus(pointerPoint(e)?.key||p.key);});
          const hover=e=>{if(pointer)return;const v=pointerPoint(e)||datum();if(v){if(state.hovered!==v.key)nodeElements.get(state.hovered)?.classList.remove('is-hovered');nodeElements.get(v.key)?.classList.add('is-hovered');showTooltip(v,e);}};
          node.addEventListener('pointerenter',hover);node.addEventListener('pointermove',hover);
          node.addEventListener('pointerleave',()=>{node.classList.remove('is-hovered');hideTooltip();});
          node.addEventListener('focus',()=>{const v=datum();if(v)showTooltip(v);});node.addEventListener('blur',hideTooltip);
          node.addEventListener('keydown',e=>{
            if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();setSelected(p.key);}
            else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key)){
              e.preventDefault();e.stopPropagation();const current=datum();let next;
              if(e.key==='Home')next=state.points[0];else if(e.key==='End')next=state.points[state.points.length-1];
              else{const dx=e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:0,dy=e.key==='ArrowUp'?-1:e.key==='ArrowDown'?1:0;
                next=state.points.filter(q=>q.key!==current.key&&(q.x-current.x)*dx+(q.y-current.y)*dy>0)
                  .sort((a,b)=>Math.hypot(a.x-current.x,a.y-current.y)-Math.hypot(b.x-current.x,b.y-current.y)||a.key.localeCompare(b.key))[0];}
              if(next){setSelected(next.key);nodeElements.get(next.key)?.focus();}
            }
          });
        }
        node.setAttribute('class',`sa-point sa-${p.kind}${p.lifecycle?' sa-'+String(p.lifecycle).replace(/[^a-z_-]/gi,''):''}${p.key===state.selected?' is-selected':''}${state.selectedTheme&&state.selectedTheme!==p.family_id?' is-muted':''}`);
        node.style.setProperty('--point-color',fill);
        node.setAttribute('aria-label',`${p.kind==='guideline'?'Guideline':p.kind==='feedback_hypothesis'?'Research hypothesis':'News observation'}: ${p.title}. ${families.get(p.family_id)?.label||p.family_id}${p.lifecycle?'. '+p.lifecycle:''}`);
        node.setAttribute('aria-pressed',String(p.key===state.selected));node.setAttribute('tabindex',p.key===state.selected||!state.selected&&p.key===state.points[0]?.key?'0':'-1');
        node.replaceChildren();
        node.append(create('circle',{class:'sa-hit',r:13,fill:'transparent'}));
        if(p.kind==='guideline'){
          node.append(create('circle',{class:'sa-point-aura',r:11,fill,opacity:.16,filter:`url(#${uid}-glow)`}),create('circle',{class:'sa-point-ring',r:7.7,fill:'none',stroke:fill}),create('circle',{class:'sa-point-core',r:4.1,fill}));
        }else if(p.kind==='feedback_hypothesis')node.append(create('path',{class:'sa-point-core',d:'M0 -4.8 L4.8 0 L0 4.8 L-4.8 0 Z',fill}));
        else node.append(create('circle',{class:'sa-evidence-aura',r:5.6,fill,opacity:.1}),create('circle',{class:'sa-point-core',r:2.7,fill}));
        node.append(create('circle',{class:'sa-selected-halo',r:12,fill:'none',stroke:fill}),create('circle',{class:'sa-selected-orbit',r:16,fill:'none',stroke:fill}));
        const at=project(p),old=oldById.get(p.id);
        if(fresh&&old&&old.key!==p.key&&state.payload.version!==state.version&&!reduced){
          const before=project(old);node.setAttribute('transform',`translate(${before.x},${before.y})`);win.requestAnimationFrame(()=>{if(node.isConnected)node.setAttribute('transform',`translate(${at.x},${at.y})`);});
        }else node.setAttribute('transform',`translate(${at.x},${at.y})`);
      }
      oldById=new Map(state.points.filter(p=>p.kind==='guideline'&&!['historical','retired'].includes(p.lifecycle)).map(p=>[p.id,p]));
      stackPoints();
    }
    function drawDock(){
      const visible=new Set(state.points.map(p=>p.family_id));
      familyDock.innerHTML=state.families.filter(c=>visible.has(c.id)).map(c=>`<button type="button" data-family="${esc(c.id)}" aria-pressed="${String(state.selectedTheme===c.id)}" style="--cluster-color:${c.color}"><i></i>${esc(c.label)}<span>${state.points.filter(p=>p.family_id===c.id).length}</span></button>`).join('');
    }
    familyDock.addEventListener('click',e=>{const button=e.target.closest('[data-family]');if(button)options.onThemeSelect?.(state.selectedTheme===button.dataset.family?'':button.dataset.family);});
    element.querySelector('.sa-controls').addEventListener('click',e=>{const action=e.target.closest('[data-sa-action]')?.dataset.saAction;if(action==='zoom-in')zoomBy(1.35);if(action==='zoom-out')zoomBy(1/1.35);if(action==='fit')resetView();});
    const position=e=>{const r=svg.getBoundingClientRect();return {x:(e.clientX-r.left)/r.width*state.width,y:(e.clientY-r.top)/r.height*state.height};};
    const wheel=e=>{e.preventDefault();zoomBy(Math.exp(-clamp(e.deltaY,-180,180)*.0028),position(e));scene.classList.remove('is-moving');};
    svg.addEventListener('wheel',wheel,{passive:false});
    svg.addEventListener('pointerdown',e=>{if(e.button!==0)return;const p=position(e);pointer={id:e.pointerId,x:p.x,y:p.y,camera:{...state.camera}};moved=false;if(!e.target.closest('[data-atlas-key],[data-family]'))svg.setPointerCapture?.(e.pointerId);});
    svg.addEventListener('pointermove',e=>{
      if(!pointer||pointer.id!==e.pointerId)return;const p=position(e),dx=p.x-pointer.x,dy=p.y-pointer.y;if(Math.hypot(dx,dy)>4)moved=true;
      if(moved){svg.setPointerCapture?.(e.pointerId);hideTooltip();svg.classList.add('is-dragging');state.camera={...pointer.camera,x:pointer.camera.x+dx,y:pointer.camera.y+dy};applyCamera(false);}
    });
    const endPointer=()=>{pointer=null;svg.classList.remove('is-dragging');};svg.addEventListener('pointerup',endPointer);svg.addEventListener('pointercancel',endPointer);
    svg.addEventListener('dblclick',e=>{if(!e.target.closest('[data-atlas-key]'))zoomBy(1.55,position(e));});
    svg.addEventListener('click',e=>{if(!moved&&!e.target.closest('[data-atlas-key]'))setSelected(null);});
    svg.addEventListener('keydown',e=>{
      if(e.key==='+'||e.key==='='){e.preventDefault();zoomBy(1.25);}else if(e.key==='-'){e.preventDefault();zoomBy(.8);}else if(e.key==='0'){e.preventDefault();resetView();}else if(e.key==='Escape'){setSelected(null);}
      else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const delta={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]}[e.key];state.camera.x+=delta[0];state.camera.y+=delta[1];applyCamera(true);}
    });
    function update(payload={}){
      if(state.destroyed)return;
      state.payload=payload;state.points=normalizePoints(payload.points);state.references=normalizePoints(payload.referencePoints||payload.points);
      state.selected=payload.selectedKey===null?null:String(payload.selectedKey??state.selected??'')||null;state.selectedTheme=String(payload.selectedTheme||'');
      const computed=groupClusters(state.references,payload.taxonomy||[]),byId=new Map(computed.map(c=>[c.id,c]));
      state.families=computed;
      state.clusters=list(payload.clusters).length?payload.clusters.filter(c=>finite(c.x)&&finite(c.y)).map((c,i)=>{
        const members=state.references.filter(p=>list(c.point_keys).includes(p.key)),family=byId.get(String(c.family_id||c.id));
        return {...family,...c,id:String(c.id),label:String(c.label||family?.label||'Semantic neighborhood'),
          color:color(c.color)||family?.color||palette[i%palette.length],points:members,
          guideline_count:members.filter(p=>p.kind==='guideline').length,observation_count:members.filter(p=>p.kind!=='guideline').length};
      }):computed;
      const beforeWidth=state.width;state.width=Math.max(320,Math.round(element.clientWidth||1000));
      state.height=state.width<560?Math.max(590,Math.min(680,Number(options.height)||680)):Number(options.height)||680;
      svg.setAttribute('viewBox',`0 0 ${state.width} ${state.height}`);svg.setAttribute('height',String(state.height));element.style.setProperty('--atlas-height',state.height+'px');
      const referenceKey=state.references.map(p=>`${p.key}:${p.x}:${p.y}:${p.family_id}`).join('|'),clusterKey=state.clusters.map(c=>`${c.id}:${c.color}`).join('|');
      if(referenceKey!==lastReferenceKey||clusterKey!==lastClustersKey||beforeWidth!==state.width){drawContours();lastReferenceKey=referenceKey;lastClustersKey=clusterKey;}
      else for(const group of contours.children)group.classList.toggle('is-muted',Boolean(state.selectedTheme&&group.dataset.family!==state.selectedTheme));
      const guidelines=state.points.filter(p=>p.kind==='guideline'&&!['historical','retired'].includes(p.lifecycle)).length,observations=state.points.filter(p=>p.kind!=='guideline').length;
      element.querySelector('.sa-meta').textContent=`${guidelines} current guidelines · ${observations} observations · ${state.families.filter(c=>state.points.some(p=>p.family_id===c.id)).length} theme families`;
      const method=String(payload.method||'');element.querySelector('.sa-method').textContent=String(payload.methodLabel||(method.includes('tsne')?'t-SNE PROJECTION':method.includes('pca')?'PCA PROJECTION':'TEXT PROJECTION'));
      drawPoints();drawNeighbors();drawTrails();drawDock();
      if(!state.hasData&&state.references.length||payload.fitKey&&payload.fitKey!==state.fitKey||beforeWidth!==state.width){fit();state.fitKey=payload.fitKey;}else applyCamera(false);
      if(state.references.length)state.hasData=true;
      state.version=payload.version??'initial';
      element.classList.toggle('is-empty',!state.points.length);
      if(!state.points.length){const empty=create('text',{x:state.width/2,y:state.height/2,'text-anchor':'middle',class:'sa-empty-label'},payload.emptyMessage||'No points match this view');nodes.append(empty);}
    }
    const resize=()=>{if(state.destroyed)return;if(frame!==null)win.cancelAnimationFrame(frame);frame=win.requestAnimationFrame(()=>{frame=null;update(state.payload);});};
    if(win.ResizeObserver){resizeObserver=new win.ResizeObserver(resize);resizeObserver.observe(element);}
    const destroy=()=>{state.destroyed=true;if(frame!==null)win.cancelAnimationFrame(frame);resizeObserver?.disconnect();element.replaceChildren();element.classList.remove('semantic-atlas');};
    update({points:[]});
    return {update,fit,zoomBy,focus,focusFamily,destroy,getCamera:()=>({...state.camera})};
  }
  return {normalizePoints,groupClusters,nearestNeighbors,pointPaintOrder,nearestPointerPoint,cameraForBounds,cameraForFamily,labelLayout,contourPaths,mount};
}));
