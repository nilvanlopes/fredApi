import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { Camera, Check, Copy, ImagePlus, Minus, Move, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import Cropper, { type Area } from 'react-easy-crop';
import { request, type PlayerProfile, type PlayerRating } from './api';
import HoloCard from './components/HoloCard';
import { Avatar, ErrorState, Field, Loading, Modal, Panel, ReadModal } from './ui';
import './Profile.css';

const positions=['ponta','levantador','central','oposto','libero'];
const skills=['passe','ataque','defesa','bloqueio','saque'] as const;
const labels:Record<string,string>={ponta:'Ponta',levantador:'Levantador',central:'Central',oposto:'Oposto',libero:'Líbero',destro:'Destro',canhoto:'Canhoto',ambidestro:'Ambidestro',masculino:'Masculino',feminino:'Feminino'};

export function ProfilePage({ id, own, authenticated, viewerPersonId, viewerUid, onLogin, onSaved }: { id?:string; own?:boolean; authenticated:boolean; viewerPersonId?:string|null; viewerUid?:string; onLogin:()=>void; onSaved?:(profile:PlayerProfile)=>void }) {
  const [revision,setRevision]=useState(0);
  const [profile,setProfile]=useState<PlayerProfile|null>(null);
  const [error,setError]=useState('');
  const [rating,setRating]=useState<PlayerRating>({stars:null,publish_identity:false});
  const [ratingLoaded,setRatingLoaded]=useState(false);
  const [ratingError,setRatingError]=useState('');
  const [saving,setSaving]=useState(false);
  const [editing,setEditing]=useState(false);
  const [photo,setPhoto]=useState(false);
  const [copied,setCopied]=useState(false);
  const [avatarRevision,setAvatarRevision]=useState(0);
  useEffect(()=>{let active=true;request<PlayerProfile>(own?'/api/me/profile':`/api/public/profiles/${id}`).then(value=>{if(active){setProfile(value);setError('');}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[id,own,revision]);
  useEffect(()=>{setRatingLoaded(false);setRatingError('');if(!authenticated||own||!id||viewerPersonId===id){setRatingLoaded(true);return;}if(!viewerPersonId){setRatingLoaded(true);setRatingError('Sua conta precisa estar vinculada a um jogador para avaliar.');return;}let active=true;request<PlayerRating>(`/api/me/ratings/${id}`).then(x=>{if(active){setRating({stars:x.stars,publish_identity:x.publish_identity});setRatingLoaded(true);}}).catch(e=>{if(active)setRatingError(e instanceof Error?e.message:'Não foi possível carregar sua avaliação.');});return()=>{active=false;};},[authenticated,own,id,revision,viewerPersonId]);
  const save=async(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();if(!profile)return;const form=new FormData(event.currentTarget);const names=String(form.get('nicknames')??'').split('\n').map(x=>x.trim()).filter(Boolean);const rawSkills=Object.fromEntries(skills.map(k=>[k,Number(form.get(k))])) as Record<typeof skills[number],number>;const selectedPositions=positions.filter(x=>form.get(`position-${x}`)==='on');const primary=String(form.get('primary_position')??'')||null;setSaving(true);setError('');try{const updated=await request<PlayerProfile>('/api/me/profile',{method:'PATCH',body:JSON.stringify({nicknames:names,bio:String(form.get('bio')??''),positions:selectedPositions,primary_position:primary,sex:String(form.get('sex')??'')||null,handedness:String(form.get('handedness')??'')||null,skills:form.get('skills-enabled')==='on'?rawSkills:null})},viewerUid);setProfile(updated);onSaved?.(updated);setEditing(false);}catch(e){setError(e instanceof Error?e.message:'Não foi possível salvar.');}finally{setSaving(false);}};
  const saveRating=async(stars:number)=>{if(!authenticated){onLogin();return;}if(!id)return;setSaving(true);setError('');try{const saved=await request<PlayerRating>(`/api/me/ratings/${id}`,{method:'PUT',body:JSON.stringify({stars,publish_identity:rating.publish_identity})},viewerUid);setRating({stars:saved.stars,publish_identity:saved.publish_identity});setRevision(x=>x+1);}catch(e){setError(e instanceof Error?e.message:'Não foi possível avaliar.');}finally{setSaving(false);}};
  const share=async()=>{const link=`${location.origin}${location.pathname}#profile/${profile?.person_id}`;try{await navigator.clipboard.writeText(link);}catch{window.prompt('Copie o link do perfil',link);}setCopied(true);setTimeout(()=>setCopied(false),1800);};
  if(!profile&&!error)return <Loading/>;
  if(!profile)return <ErrorState message={error} retry={()=>setRevision(x=>x+1)}/>;
  const avatar=profile.avatar_url?`${profile.avatar_url}${profile.avatar_url.includes('?')?'&':'?'}v=${avatarRevision}`:null;
  const isOwnRating=Boolean(own||(id&&viewerPersonId===id));
  return <div className="player-profile"><Panel className="profile-hero"><div className="profile-identity"><div className="profile-avatar">{avatar?<img src={avatar} alt=""/>:<Avatar name={profile.name}/ >}{own&&authenticated?<button className="profile-camera" aria-label="Editar foto" onClick={()=>setPhoto(true)}><Camera size={17}/></button>:null}</div><div className="profile-title"><span className="eyebrow">PERFIL DO JOGADOR</span><h1>{profile.name}</h1>{profile.nicknames.length?<p className="profile-nicknames">{profile.nicknames.join(' · ')}</p>:null}{profile.bio?<p className="profile-bio">{profile.bio}</p>:null}</div><div className="profile-actions">{own?<button className="button secondary" onClick={()=>setEditing(true)}><Pencil size={16}/>Editar perfil</button>:null}<button className="button secondary" onClick={share}><Copy size={16}/>{copied?'Link copiado':'Compartilhar'}</button></div></div><div className="profile-rating-summary"><div aria-label={profile.rating_average===null?'Sem avaliações':`Média ${profile.rating_average.toFixed(1)} de 5`} className="profile-stars">{[1,2,3,4,5].map(n=><StarMark key={n} value={profile.rating_average??0} position={n}/>)}</div><strong>{profile.rating_average===null?'—':profile.rating_average.toFixed(1)}</strong><span>{profile.rating_count===0?'Nenhuma avaliação':profile.rating_count===1?'1 avaliação':`${profile.rating_count} avaliações`}</span><i/><strong>{profile.games_count}</strong><span>partidas</span></div></Panel>
    <div className="profile-columns"><Panel title="Sobre">{profile.positions.length?<div className="profile-detail"><small>Posições</small><p>{profile.positions.map(x=><span className="profile-chip" key={x}>{labels[x]??x}{x===profile.primary_position?' · principal':''}</span>)}</p></div>:null}<ProfileValue label="Sexo" value={profile.sex?labels[profile.sex]:null}/><ProfileValue label="Mão dominante" value={profile.handedness?labels[profile.handedness]:null}/><ProfileRadar skills={profile.skills}/></Panel><Panel title={isOwnRating?'Avaliações':'Avaliar jogador'}>{isOwnRating?<OwnRatingSummary profile={profile}/>:<><p className="muted">Sua avaliação é geral e pode ser alterada quando quiser.</p>{authenticated?<>{ratingError?<><p className="profile-error" role="alert">{ratingError}</p>{viewerPersonId?<button className="button secondary" onClick={()=>setRevision(v=>v+1)}>Tentar novamente</button>:null}</>:!ratingLoaded?<Loading/>:<><div className="rating-picker" role="group" aria-label="Sua avaliação">{[1,2,3,4,5].map(n=><button key={n} type="button" disabled={saving} aria-label={`${n} estrelas`} aria-pressed={rating.stars===n} onClick={()=>saveRating(n)}><Star fill={rating.stars!==null&&n<=rating.stars?'currentColor':'none'}/></button>)}</div><label className="checkbox-field"><input type="checkbox" checked={rating.publish_identity} disabled={saving} onChange={async e=>{const publish_identity=e.target.checked;if(rating.stars===null){setRating(v=>({...v,publish_identity}));return;}if(!id)return;setSaving(true);setError('');try{const saved=await request<PlayerRating>(`/api/me/ratings/${id}`,{method:'PUT',body:JSON.stringify({stars:rating.stars,publish_identity})},viewerUid);setRating({stars:saved.stars,publish_identity:saved.publish_identity});}catch(error){setError(error instanceof Error?error.message:'Não foi possível salvar a preferência.');setRating(v=>({...v,publish_identity:!publish_identity}));}finally{setSaving(false);}}}/>Permitir divulgar meu nome e minha nota</label><small className="profile-rating-note">O perfil público mostra somente a média e a quantidade de avaliações.</small></>}</>:<button className="button" onClick={onLogin}>Entrar para avaliar</button>}</>}</Panel></div>{error?<p className="profile-error" role="alert">{error}</p>:null}
    {editing?<EditProfile profile={profile} error={error} busy={saving} close={()=>setEditing(false)} submit={save}/>:null}{photo&&own?<PhotoEditor uid={viewerUid} initialCrop={profile.photo_crop} close={()=>setPhoto(false)} saved={updated=>{setPhoto(false);setAvatarRevision(x=>x+1);setRevision(x=>x+1);onSaved?.(updated);}}/>:null}
  </div>;
}

function OwnRatingSummary({profile}:{profile:PlayerProfile}){
  if(profile.rating_count===0)return <p className="muted">Nenhuma avaliação</p>;
  const average=profile.rating_average;
  return <div className="profile-own-rating-summary"><div aria-label={average===null?'Média indisponível':`Média ${average.toFixed(1)} de 5`} className="profile-stars">{[1,2,3,4,5].map(n=><StarMark key={n} value={average??0} position={n}/>)}</div><p><strong>Média {average===null?'—':average.toFixed(1)} de 5</strong><span>{profile.rating_count} {profile.rating_count===1?'avaliação':'avaliações'}</span></p></div>;
}

export function ProfileQuickCard({ id, name, onClose, onView, mode='modal', anchor, onEnter, onLeave }: { id:string; name:string; onClose:()=>void; onView:(id:string)=>void; mode?:'modal'|'hover'; anchor?:HTMLElement|null; onEnter?:()=>void; onLeave?:()=>void }) {
  const [profile, setProfile] = useState<PlayerProfile|null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLElement|null>(null);
  const [position,setPosition]=useState<{left:number;top:number}|null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setProfile(null);
    request<PlayerProfile>(`/api/public/profiles/${id}`, { signal:controller.signal })
      .then(value => { if (!controller.signal.aborted) setProfile(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o perfil.'); });
    return () => controller.abort();
  }, [id, revision]);
  useEffect(() => {
    if(mode==='modal') trigger.current = anchor ?? document.activeElement as HTMLElement;
    const dismiss = () => { onClose(); if(mode==='modal') trigger.current?.focus(); };
    const keyboard = (event:KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
      if (event.key === 'Tab' && ref.current) {
        const controls = [...ref.current.querySelectorAll<HTMLElement>('button,a,[tabindex="0"]')];
        const first = controls[0], last = controls.at(-1);
        if (!first || !last) { event.preventDefault(); ref.current.focus(); return; }
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    const outside = (event:PointerEvent) => {
      const target=event.target as Node;
      if(ref.current?.contains(target)||anchor?.contains(target))return;
      dismiss();
    };
    if(mode==='modal') document.addEventListener('keydown', keyboard);
    document.addEventListener('pointerdown', outside);
    if(mode==='modal') (ref.current?.querySelector<HTMLElement>('button')??ref.current)?.focus();
    return () => { if(mode==='modal')document.removeEventListener('keydown', keyboard); document.removeEventListener('pointerdown', outside); };
  }, [id, onClose, mode, anchor]);
  useLayoutEffect(()=>{
    // Loading may replace the plain wrapper with HoloCard and remove the focused control.
    const focusedControl=ref.current?.querySelectorAll<HTMLElement>('button,a,[tabindex="0"]');
    const active=document.activeElement;
    if(mode==='modal'&&(profile||error)&&(!ref.current?.contains(active)||active===ref.current||!focusedControl?.length)){
      ref.current?.querySelector<HTMLElement>('button')?.focus();
    }
  },[mode,profile,error]);
  useEffect(()=>{
    if(mode!=='hover'||!anchor)return;
    const update=()=>{const rect=anchor.getBoundingClientRect();const card=ref.current?.getBoundingClientRect();const width=card?.width??320;const height=card?.height??130;const left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8));const top=rect.bottom+8+height<=window.innerHeight?rect.bottom+8:Math.max(8,rect.top-height-8);setPosition({left,top});};
    update();window.addEventListener('resize',update);window.addEventListener('scroll',update,true);
    const keyboard=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();onClose();}};
    document.addEventListener('keydown',keyboard);
    return()=>{window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true);document.removeEventListener('keydown',keyboard);};
  },[mode,anchor,onClose,profile,error]);
  const holoEnabled=profile?.is_subscriber===true;
  const content=<div className="profile-quick-content">
    {holoEnabled?<span className="profile-quick-vip-pattern" aria-hidden="true"/>:null}
    <div className="profile-quick-portrait"><span className="profile-quick-avatar"><Avatar name={profile?.name ?? name} src={profile?.avatar_url}/></span></div>
    <div className="profile-quick-details">
      <div className="profile-quick-header"><strong>{profile?.name ?? name}</strong></div>
      {error ? <><p role="alert">{error}</p><button className="text-link" onClick={() => setRevision(value => value + 1)}>Tentar novamente</button></> : profile ? <div className="profile-quick-stats"><div className="profile-quick-rating"><div className="profile-stars" aria-hidden="true">{[1,2,3,4,5].map(n=><StarMark key={n} value={profile.rating_average??0} position={n}/>)}</div><span>{profile.rating_average === null ? 'Sem avaliações' : profile.rating_average.toFixed(1).replace('.', ',')}</span></div><div className="profile-quick-games"><span className="profile-quick-court" aria-hidden="true"/><span>{profile.games_count} partidas</span></div></div> : <p role="status">Carregando perfil…</p>}
      <button className="profile-quick-view" onClick={() => onView(id)}>Ver perfil<span aria-hidden="true">→</span></button>
    </div>
  </div>;
  const card=<div ref={ref} className={`profile-quick ${mode==='hover'?'profile-quick-hover':''}${holoEnabled?' profile-quick-subscriber':''}`} style={mode==='hover'&&position?{left:position.left,top:position.top}:undefined} role="dialog" aria-modal={mode==='modal'?true:undefined} aria-label={`Perfil resumido de ${name}`} tabIndex={mode==='modal'?-1:undefined} onMouseEnter={mode==='hover'?onEnter:undefined} onMouseLeave={mode==='hover'?onLeave:undefined} onFocus={mode==='hover'?onEnter:undefined} onBlur={mode==='hover'?event=>{if(!event.currentTarget.contains(event.relatedTarget as Node|null))onLeave?.();}:undefined}>
    {holoEnabled?<HoloCard image="/holo-subscriber.svg" preset="gold" idle={false} maxDpr={mode==='modal'?1:2} maxFps={mode==='modal'?30:60} tiltMax={8} hoverScale={1.01} width={320} radius={24} shadow={false} className="profile-quick-holo" style={{width:'100%',aspectRatio:'auto'}}>{content}</HoloCard>:content}
  </div>;
  return mode==='hover'?createPortal(card,document.body):<div className="profile-quick-backdrop">{card}</div>;
}
function StarMark({value,position}:{value:number;position:number}){const amount=Math.max(0,Math.min(1,value-position+1))*100;return <span className="profile-star-mark" aria-hidden="true"><Star size={18}/><Star className="profile-star-fill" size={18} style={{clipPath:`inset(0 ${100-amount}% 0 0)`}}/></span>}
function ProfileValue({label,value}:{label:string;value:string|null}){return <div className="profile-detail"><small>{label}</small><p>{value??'Não informado'}</p></div>}
function ProfileRadar({skills}:{skills:PlayerProfile['skills']}){const values=skills?[skills.passe,skills.ataque,skills.defesa,skills.bloqueio,skills.saque]:[];const points=useMemo(()=>values.map((v,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;const r=v*.85;return `${100+Math.cos(a)*r},${100+Math.sin(a)*r}`}).join(' '), [skills]);return <div className="profile-radar-wrap"><small>Habilidades autodeclaradas</small>{skills?<><svg className="profile-radar" viewBox="0 0 200 200" role="img" aria-label="Gráfico radar das habilidades autodeclaradas"><polygon points="100,15 181,74 150,169 50,169 19,74"/><polygon className="profile-radar-data" points={points}/>{skillsLabel.map((label,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;return <text key={label} x={100+Math.cos(a)*90} y={100+Math.sin(a)*90} textAnchor="middle" dominantBaseline="middle">{label}</text>})}</svg><div className="profile-skill-values">{values.map((v,i)=><span key={skillsLabel[i]}>{skillsLabel[i]} {v}</span>)}</div></>:<p className="muted">Não informadas</p>}</div>}
const skillsLabel=['Passe','Ataque','Defesa','Bloqueio','Saque'];
function EditProfile({profile,error,busy,close,submit}:{profile:PlayerProfile;error:string;busy:boolean;close:()=>void;submit:(e:FormEvent<HTMLFormElement>)=>void}){
 const [selectedPositions,setSelectedPositions]=useState(profile.positions);const [primary,setPrimary]=useState(profile.primary_position??'');const [skillsEnabled,setSkillsEnabled]=useState(Boolean(profile.skills));const [skillValues,setSkillValues]=useState(()=>Object.fromEntries(skills.map(k=>[k,profile.skills?.[k]??50])) as Record<typeof skills[number],number>);
 const preview=skillsEnabled?Object.fromEntries(skills.map(k=>[k,skillValues[k]])) as NonNullable<PlayerProfile['skills']>:null;
 return <Modal title="Editar perfil" onClose={close} onSubmit={submit} busy={busy} submit="Salvar perfil">{error?<p role="alert" className="profile-error">{error}</p>:null}<p className="muted">Seu nome atual não pode ser alterado aqui.</p><Field label="Apelidos para apresentação"><textarea name="nicknames" rows={3} defaultValue={profile.nicknames.join('\n')} placeholder="Um apelido por linha"/></Field><Field label="Frase do perfil"><input name="bio" maxLength={140} defaultValue={profile.bio} placeholder="Conte um pouco sobre você"/><small>Até 140 caracteres, em uma linha.</small></Field><fieldset><legend>Posições</legend>{positions.map(p=><label key={p} className="profile-option"><input type="checkbox" name={`position-${p}`} checked={selectedPositions.includes(p)} onChange={e=>{const next=e.target.checked?[...selectedPositions,p]:selectedPositions.filter(x=>x!==p);setSelectedPositions(next);if(e.target.checked&&!primary)setPrimary(p);else if(!next.includes(primary))setPrimary(next[0]??'');}}/>{labels[p]}</label>)}<Field label="Posição principal"><select name="primary_position" value={primary} onChange={e=>setPrimary(e.target.value)}><option value="" disabled={selectedPositions.length>0}>Não informada</option>{positions.map(p=><option key={p} value={p} disabled={!selectedPositions.includes(p)}>{labels[p]}</option>)}</select></Field></fieldset><Field label="Sexo"><select name="sex" defaultValue={profile.sex??''}><option value="">Não informado</option><option value="masculino">Masculino</option><option value="feminino">Feminino</option></select></Field><Field label="Mão dominante"><select name="handedness" defaultValue={profile.handedness??''}><option value="">Não informado</option><option value="destro">Destro</option><option value="canhoto">Canhoto</option><option value="ambidestro">Ambidestro</option></select></Field><label className="checkbox-field"><input type="checkbox" name="skills-enabled" checked={skillsEnabled} onChange={e=>setSkillsEnabled(e.target.checked)}/>Informar minhas habilidades</label>{skills.map(k=><Field key={k} label={`${labelsSkill[k]} (0–100)`}><input aria-label={`${labelsSkill[k]} (0–100)`} name={k} type="range" min="0" max="100" disabled={!skillsEnabled} value={skillValues[k]} onChange={e=>setSkillValues(v=>({...v,[k]:Number(e.target.value)}))}/><output>{skillsEnabled?skillValues[k]:'—'}</output></Field>)}<div className="profile-editor-preview"><small>Prévia das habilidades autodeclaradas</small><ProfileRadar skills={preview}/></div></Modal>
}
const labelsSkill:Record<typeof skills[number],string>={passe:'Passe',ataque:'Ataque',defesa:'Defesa',bloqueio:'Bloqueio',saque:'Saque'};
function PhotoEditor({uid,initialCrop,close,saved}:{uid?:string;initialCrop?:PlayerProfile['photo_crop'];close:()=>void;saved:(profile:PlayerProfile)=>void}) {
  const [src,setSrc]=useState('');
  const [file,setFile]=useState<File|null>(null);
  const [crop,setCrop]=useState({x:0,y:0});
  const [zoom,setZoom]=useState(1);
  const [area,setArea]=useState<Area|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const input=useRef<HTMLInputElement>(null);
  const urls=useRef<string[]>([]);
  const selected=useRef(false);

  useEffect(()=>{
    let active=true;
    fetch('/api/me/profile/photo/source',{credentials:'same-origin'})
      .then(async response=>{
        if(!response.ok)return;
        const blob=await response.blob();
        if(!active)return;
        const url=URL.createObjectURL(blob);
        urls.current.push(url);
        if(active&&!selected.current)setSrc(url);
      })
      .catch(()=>{});
    return()=>{
      active=false;
      urls.current.forEach(URL.revokeObjectURL);
    };
  },[]);

  const choose=(selectedFile?:File)=>{
    if(!selectedFile)return;
    if(!['image/jpeg','image/png','image/webp'].includes(selectedFile.type)||selectedFile.size>10*1024*1024){
      setError('Escolha uma imagem JPEG, PNG ou WebP de até 10 MiB.');
      return;
    }
    setError('');
    selected.current=true;
    setFile(selectedFile);
    const url=URL.createObjectURL(selectedFile);
    urls.current.push(url);
    setSrc(url);
    setArea(null);
    setCrop({x:0,y:0});
    setZoom(1);
  };

  const save=async()=>{
    if(!area)return;
    setBusy(true);
    setError('');
    try{
      const cropBody=JSON.stringify({x:Math.round(area.x),y:Math.round(area.y),width:Math.round(area.width),height:Math.round(area.height)});
      let updated:PlayerProfile;
      if(file){
        const data=new FormData();
        data.append('file',file);
        data.append('crop',cropBody);
        updated=await request<PlayerProfile>('/api/me/profile/photo',{method:'POST',body:data},uid);
      }else{
        updated=await request<PlayerProfile>('/api/me/profile/photo',{method:'PATCH',body:cropBody},uid);
      }
      saved(updated);
    }catch(reason){
      setError(reason instanceof Error?reason.message:'Não foi possível salvar a foto.');
    }finally{
      setBusy(false);
    }
  };

  const remove=async()=>{
    setBusy(true);
    setError('');
    try{
      const updated=await request<PlayerProfile>('/api/me/profile/photo',{method:'DELETE'},uid);
      saved(updated);
    }catch(reason){
      setError(reason instanceof Error?reason.message:'Não foi possível remover a foto.');
    }finally{
      setBusy(false);
    }
  };

  const adjustZoom=(amount:number)=>setZoom(current=>Math.max(1,Math.min(3,Math.round((current+amount)*100)/100)));

  return <ReadModal title="Foto do perfil" className="photo-dialog" showFooter={false} onClose={()=>{if(!busy)close();}}>
    <div className="photo-crop">
      {src?<>
        <p className="photo-instructions">Arraste a foto para ajustar o enquadramento.</p>
        <div className="crop-area">
          <Cropper image={src} crop={crop} zoom={zoom} minZoom={1} maxZoom={3} aspect={1} cropShape="rect" showGrid initialCroppedAreaPixels={!file?initialCrop??undefined:undefined} onCropChange={setCrop} onZoomChange={setZoom} onCropComplete={(_,pixels)=>setArea(pixels)}/>
        </div>
        <p className="photo-crop-hint"><Move size={16}/>Arraste para reposicionar</p>
      </>:<>
        <p className="photo-instructions">Escolha uma foto para o seu perfil.</p>
        <div className="photo-empty"><ImagePlus size={48}/><strong>Adicione sua foto</strong><small>JPEG, PNG ou WebP · até 10 MiB</small></div>
      </>}
      <input hidden className="photo-file-input" aria-label="Selecionar foto do perfil" ref={input} type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event=>{choose(event.currentTarget.files?.[0]);event.currentTarget.value='';}}/>
      {src?<div className="photo-zoom">
        <label htmlFor="profile-photo-zoom">Zoom</label>
        <button type="button" className="icon-button" aria-label="Diminuir zoom" disabled={busy||zoom<=1} onClick={()=>adjustZoom(-0.1)}><Minus size={16}/></button>
        <input id="profile-photo-zoom" type="range" min="1" max="3" step="0.01" value={zoom} disabled={busy} onChange={event=>setZoom(Number(event.target.value))}/>
        <button type="button" className="icon-button" aria-label="Aumentar zoom" disabled={busy||zoom>=3} onClick={()=>adjustZoom(0.1)}><Plus size={16}/></button>
      </div>:null}
      <div className="photo-tools">
        <button type="button" className="button secondary photo-choose" disabled={busy} onClick={()=>input.current?.click()}><ImagePlus size={18}/>{src?'Trocar foto':'Escolher foto'}</button>
        {src?<button type="button" className="button secondary photo-remove" disabled={busy} onClick={remove}><Trash2 size={16}/>Remover foto</button>:null}
      </div>
      {error?<p role="alert" className="photo-error">{error}</p>:null}
      <footer className="photo-actions">
        <button type="button" className="button secondary" disabled={busy} onClick={close}>Cancelar</button>
        <button type="button" className="button" disabled={busy||!area} onClick={save}><Check size={16}/>Salvar foto</button>
      </footer>
    </div>
  </ReadModal>;
}
