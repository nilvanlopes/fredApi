import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, act, within } from '@testing-library/react';
import { PlayerProfileTrigger } from './PlayerProfileTrigger';

const profile={person_id:'p-1',name:'Ana Lima',nicknames:[],bio:'hidden',positions:[],primary_position:null,sex:null,handedness:null,skills:null,avatar_url:null,rating_average:4.5,rating_count:3,games_count:12};
let hoverMatches=false;
function setupMedia(){vi.stubGlobal('matchMedia',vi.fn((query:string)=>({matches:query.includes('hover: hover')&&hoverMatches,media:query,onchange:null,addEventListener:vi.fn(),removeEventListener:vi.fn(),dispatchEvent:vi.fn()})));}
function setupFetch(){vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>profile} as Response)));}

afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();hoverMatches=false;});

describe('PlayerProfileTrigger',()=>{
  it('opens by desktop hover, stays open when the pointer enters the card, and navigates',async()=>{
    hoverMatches=true;setupMedia();setupFetch();vi.useFakeTimers();
    render(<PlayerProfileTrigger personId="p-1" name="Ana Lima"/>);
    const trigger=screen.getByRole('button',{name:'Ana Lima'});
    fireEvent.mouseEnter(trigger);
    act(()=>{vi.advanceTimersByTime(149);});expect(screen.queryByRole('dialog')).toBeNull();
    act(()=>{vi.advanceTimersByTime(1);});
    await act(async()=>{await Promise.resolve();await Promise.resolve();});
    const card=screen.getByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(screen.queryByRole('button',{name:'Fechar perfil'})).toBeNull();
    fireEvent.mouseLeave(trigger);fireEvent.mouseEnter(card);
    act(()=>{vi.advanceTimersByTime(250);});
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Ver perfil'}));
    expect(location.hash).toBe('#profile/p-1');
  });

  it('opens a dismissible modal by click on touch devices and with no hover capability',async()=>{
    hoverMatches=false;setupMedia();setupFetch();
    render(<PlayerProfileTrigger personId="p-1" name="Ana Lima"/>);
    const trigger=screen.getByRole('button',{name:'Ana Lima'});
    fireEvent.mouseEnter(trigger);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(trigger);
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(within(dialog).queryByRole('button',{name:'Fechar perfil'})).toBeNull();
    fireEvent.pointerDown(trigger);
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.click(trigger);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(trigger);
    await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button',{name:'Ana Lima'}));
  });

  it('fecha no clique fora sem perder a tolerância ao mover o ponteiro para o card',async()=>{
    hoverMatches=true;setupMedia();setupFetch();vi.useFakeTimers();
    render(<PlayerProfileTrigger personId="p-1" name="Ana Lima"/>);
    const trigger=screen.getByRole('button',{name:'Ana Lima'});
    fireEvent.mouseEnter(trigger);
    act(()=>{vi.advanceTimersByTime(150);});
    await act(async()=>{await Promise.resolve();await Promise.resolve();});
    const card=screen.getByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    fireEvent.mouseLeave(trigger);fireEvent.mouseEnter(card);
    act(()=>{vi.advanceTimersByTime(250);});
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('uses the modal mode for keyboard activation on desktop',async()=>{
    hoverMatches=true;setupMedia();setupFetch();vi.useFakeTimers();
    render(<PlayerProfileTrigger personId="p-1" name="Ana Lima"/>);
    const trigger=screen.getByRole('button',{name:'Ana Lima'});
    act(()=>trigger.focus());
    fireEvent.click(trigger,{detail:0});
    await act(async()=>{await Promise.resolve();await Promise.resolve();});
    const dialog=screen.getByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    act(()=>{vi.advanceTimersByTime(1000);});
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.keyDown(document,{key:'Escape'});
    act(()=>{vi.advanceTimersByTime(1000);});
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('converts a hover preview to a modal on keyboard activation and closes on the next activation',async()=>{
    hoverMatches=true;setupMedia();setupFetch();vi.useFakeTimers();
    render(<PlayerProfileTrigger personId="p-1" name="Ana Lima"/>);
    const trigger=screen.getByRole('button',{name:'Ana Lima'});
    fireEvent.mouseEnter(trigger);
    act(()=>{vi.advanceTimersByTime(150);});
    await act(async()=>{await Promise.resolve();await Promise.resolve();});
    expect(screen.getByRole('dialog').getAttribute('aria-modal')).toBeNull();
    fireEvent.click(trigger,{detail:0});
    expect(screen.getByRole('dialog').getAttribute('aria-modal')).toBe('true');
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(trigger,{detail:0});
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
  });

  it('renders plain text when the player has no public person id',()=>{
    setupMedia();render(<PlayerProfileTrigger personId={null} name="Sem vínculo"/>);
    expect(screen.getByText('Sem vínculo').tagName).toBe('SPAN');
    expect(screen.queryByRole('button')).toBeNull();
  });
});
