import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ProfileQuickCard } from './Profile';

vi.mock('./components/HoloCard',()=>({default:({children,image,preset,maxDpr,maxFps,idle,shadow}:{children:ReactNode;image:string;preset:string;maxDpr:number;maxFps:number;idle:boolean;shadow:boolean})=><div data-testid="holo-card" data-image={image} data-preset={preset} data-max-dpr={maxDpr} data-max-fps={maxFps} data-idle={String(idle)} data-shadow={String(shadow)}>{children}</div>}));

const profile={person_id:'p-1',name:'Ana Lima',nicknames:['Aninha'],bio:'bio privada',positions:['ponta'],primary_position:'ponta',sex:null,handedness:null,skills:null,avatar_url:'/avatar.webp',rating_average:4.5,rating_count:8,games_count:21,is_subscriber:true};
function mockProfile(isSubscriber:boolean,avatarUrl:string|null=profile.avatar_url){vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...profile,is_subscriber:isSubscriber,avatar_url:avatarUrl})} as Response)));}
function renderQuick(mode:'hover'|'modal',onView=vi.fn()){const anchor=document.createElement('button');document.body.append(anchor);const result=render(<ProfileQuickCard id="p-1" name="Ana Lima" mode={mode} anchor={anchor} onClose={vi.fn()} onView={onView}/>);return{...result,anchor,onView};}

afterEach(()=>{cleanup();document.querySelectorAll('body > button').forEach(node=>node.remove());vi.restoreAllMocks();});

describe('assinante na quick card',()=>{
  it('monta HoloCard no hover de assinante, exibe a foto e navega pelo controle DOM',async()=>{
    mockProfile(true);const onView=vi.fn();renderQuick('hover',onView);
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    const holo=await within(dialog).findByTestId('holo-card');
    expect(holo.getAttribute('data-image')).toBe('/holo-subscriber.svg');
    expect(holo.getAttribute('data-preset')).toBe('gold');
    expect(holo.getAttribute('data-max-dpr')).toBe('2');
    expect(holo.getAttribute('data-max-fps')).toBe('60');
    expect(holo.getAttribute('data-idle')).toBe('false');
    expect(holo.getAttribute('data-shadow')).toBe('false');
    expect(dialog.classList.contains('profile-quick-subscriber')).toBe(true);
    expect(dialog.querySelector('.profile-quick-vip-pattern')?.getAttribute('aria-hidden')).toBe('true');
    expect(within(dialog).queryByRole('button',{name:'Fechar perfil'})).toBeNull();
    expect(within(dialog).getByText('4,5')).toBeTruthy();
    expect(within(dialog).getByText('21 partidas')).toBeTruthy();
    expect(within(dialog).queryByText('bio privada')).toBeNull();
    expect(dialog.querySelector('.profile-quick-portrait .profile-quick-avatar img')?.getAttribute('src')).toContain('/avatar.webp');
    fireEvent.click(within(dialog).getByRole('button',{name:'Ver perfil'}));
    expect(onView).toHaveBeenCalledWith('p-1');
  });

  it('não monta HoloCard para não assinante no hover',async()=>{
    mockProfile(false);renderQuick('hover');
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(await within(dialog).findByText('21 partidas')).toBeTruthy();
    expect(within(dialog).queryByTestId('holo-card')).toBeNull();
    expect(dialog.classList.contains('profile-quick-subscriber')).toBe(false);
    expect(dialog.querySelector('.profile-quick-vip-pattern')).toBeNull();
    expect(dialog.querySelector('.profile-quick-avatar img')?.getAttribute('src')).toContain('/avatar.webp');
  });

  it('monta HoloCard no modo modal de assinante, mantém a foto e restaura foco no controle',async()=>{
    mockProfile(true);renderQuick('modal');
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    const holo=await within(dialog).findByTestId('holo-card');
    expect(holo.getAttribute('data-max-dpr')).toBe('1');
    expect(holo.getAttribute('data-max-fps')).toBe('30');
    expect(dialog.querySelector('.profile-quick-vip-pattern')?.getAttribute('aria-hidden')).toBe('true');
    expect(await within(dialog).findByText('21 partidas')).toBeTruthy();
    expect(dialog.querySelector('.profile-quick-portrait .profile-quick-avatar img')?.getAttribute('src')).toContain('/avatar.webp');
    await waitFor(()=>expect(document.activeElement).toBe(within(dialog).getByRole('button',{name:'Ver perfil'})));
  });

  it('usa as iniciais quando o perfil não tem foto',async()=>{
    mockProfile(false,null);renderQuick('modal');
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    expect(await within(dialog).findByText('21 partidas')).toBeTruthy();
    expect(dialog.querySelector('.profile-quick-avatar img')).toBeNull();
    expect(within(dialog).getByText('AL')).toBeTruthy();
  });

  it('mantém o mesmo nome e fallback quando a foto de assinante falha',async()=>{
    mockProfile(true);const {onView}=renderQuick('modal');
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    await within(dialog).findByTestId('holo-card');
    fireEvent.error(dialog.querySelector('.profile-quick-avatar img')!);
    expect(within(dialog).getByText('AL')).toBeTruthy();
    expect(within(dialog).getByText('Ana Lima')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button',{name:'Ver perfil'}));
    expect(onView).toHaveBeenCalledWith('p-1');
  });

  it('remove o material VIP ao abrir outro jogador sem assinatura atual',async()=>{
    mockProfile(true);const {rerender}=renderQuick('modal');
    const dialog=await screen.findByRole('dialog',{name:'Perfil resumido de Ana Lima'});
    await within(dialog).findByTestId('holo-card');
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...profile,person_id:'p-2',name:'João Souza',is_subscriber:false})} as Response)));
    rerender(<ProfileQuickCard id="p-2" name="João Souza" onClose={vi.fn()} onView={vi.fn()}/>);
    await waitFor(()=>expect(within(dialog).queryByTestId('holo-card')).toBeNull());
    expect(await within(dialog).findByText('21 partidas')).toBeTruthy();
    expect(dialog.classList.contains('profile-quick-subscriber')).toBe(false);
    expect(dialog.querySelector('.profile-quick-vip-pattern')).toBeNull();
    expect(within(dialog).getByText('João Souza')).toBeTruthy();
    expect(within(dialog).getAllByRole('button')).toHaveLength(1);
  });


  it('mantém nome longo, zero partidas e estado sem avaliações no card especial',async()=>{
    const name='Ana Carolina Albuquerque de Oliveira';
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...profile,name,avatar_url:null,rating_average:null,rating_count:0,games_count:0})} as Response)));
    render(<ProfileQuickCard id="p-1" name={name} onClose={vi.fn()} onView={vi.fn()}/>);
    const dialog=await screen.findByRole('dialog',{name:`Perfil resumido de ${name}`});
    await within(dialog).findByTestId('holo-card');
    expect(within(dialog).getByText(name)).toBeTruthy();
    expect(within(dialog).getByText('Sem avaliações')).toBeTruthy();
    expect(within(dialog).getByText('0 partidas')).toBeTruthy();
    expect(within(dialog).getByRole('button',{name:'Ver perfil'})).toBeTruthy();
  });

});
