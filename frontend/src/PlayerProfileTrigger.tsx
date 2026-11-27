import { useCallback, useEffect, useRef, useState } from 'react';
import { ProfileQuickCard } from './Profile';

/** Name-only trigger for a public player profile summary. */
export function PlayerProfileTrigger({ personId, name }: { personId:string|null|undefined; name:string }) {
  const [open,setOpen]=useState(false);
  const [hoverCapable,setHoverCapable]=useState(false);
  const [cardMode,setCardMode]=useState<'hover'|'modal'>('modal');
  const trigger=useRef<HTMLButtonElement>(null);
  const openTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const closeTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const clearOpen=()=>{if(openTimer.current)clearTimeout(openTimer.current);openTimer.current=null;};
  const clearClose=()=>{if(closeTimer.current)clearTimeout(closeTimer.current);closeTimer.current=null;};
  const dismiss=useCallback(()=>{clearOpen();clearClose();setOpen(false);},[]);
  useEffect(()=>{
    if(typeof window.matchMedia!=='function'){setHoverCapable(false);return;}
    const query=window.matchMedia('(hover: hover) and (pointer: fine)');
    const update=()=>setHoverCapable(query.matches);
    update();query.addEventListener?.('change',update);
    return()=>{query.removeEventListener?.('change',update);clearOpen();clearClose();};
  },[]);
  if(!personId)return <span>{name}</span>;
  const enter=()=>{if(!hoverCapable)return;setCardMode('hover');clearClose();clearOpen();openTimer.current=setTimeout(()=>setOpen(true),150);};
  const leave=()=>{if(!hoverCapable||cardMode!=='hover')return;clearOpen();clearClose();closeTimer.current=setTimeout(()=>setOpen(false),200);};
  return <>
    <button ref={trigger} type="button" className="profile-name-link" aria-haspopup="dialog" aria-expanded={open} onMouseEnter={enter} onMouseLeave={leave} onBlur={leave} onClick={event=>{clearOpen();clearClose();setCardMode(event.detail===0||!hoverCapable?'modal':'hover');setOpen(value=>event.detail===0&&cardMode==='hover'?true:!value);}}>{name}</button>
    {open?<ProfileQuickCard id={personId} name={name} mode={cardMode} anchor={trigger.current} onEnter={clearClose} onLeave={leave} onClose={dismiss} onView={id=>{location.hash=`profile/${id}`;dismiss();}}/>:null}
  </>;
}
