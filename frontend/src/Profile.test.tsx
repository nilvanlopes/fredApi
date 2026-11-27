import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ProfilePage } from './Profile';
import { request } from './api';

const profile={person_id:'person-1',name:'Ana Lima',nicknames:['Aninha'],bio:'Jogo desde criança.',positions:['ponta','libero'],primary_position:'ponta',sex:null,handedness:null,skills:null,avatar_url:null,rating_average:4.3,rating_count:3,games_count:12};
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe('ProfilePage',()=>{
  it('mostra o perfil público e oculta dados opcionais não informados',async()=>{
    vi.stubGlobal('fetch',vi.fn(async input=>({ok:true,json:async()=>String(input).includes('/ratings/')?{stars:null,publish_identity:false,rating_average:4.3,rating_count:3}:profile} as Response)));
    render(<ProfilePage id="person-1" authenticated={false} onLogin={()=>{}}/>);
    expect(await screen.findByRole('heading',{name:'Ana Lima'})).toBeTruthy();
    expect(screen.getByText('Aninha')).toBeTruthy();
    expect(screen.getByText('Jogo desde criança.')).toBeTruthy();
    expect(screen.getByText('Sexo')).toBeTruthy();
    expect(screen.getByText('Mão dominante')).toBeTruthy();
    expect(screen.getAllByText('Não informado')).toHaveLength(2);
    expect(screen.getByText('Não informadas')).toBeTruthy();
    expect(screen.getByText('4.3')).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
  });

  it('oferece entrar antes de avaliar quando a pessoa não está autenticada',async()=>{
    vi.stubGlobal('fetch',vi.fn(async input=>({ok:true,json:async()=>String(input).includes('/ratings/')?{stars:null,publish_identity:false,rating_average:4.3,rating_count:3}:profile} as Response)));
    const onLogin=vi.fn();
    render(<ProfilePage id="person-1" authenticated={false} onLogin={onLogin}/>);
    const ratingHeading=await screen.findByRole('heading',{name:'Avaliar jogador'});
    expect(within(ratingHeading.closest('section')!).getByRole('button',{name:'Entrar para avaliar'})).toBeTruthy();
    fireEvent.click(await screen.findByRole('button',{name:'Entrar para avaliar'}));
    expect(onLogin).toHaveBeenCalledOnce();
    expect(screen.queryByRole('group',{name:'Sua avaliação'})).toBeNull();
  });

  it('mostra o estado vazio de avaliações no perfil próprio',async()=>{
    const emptyProfile={...profile,rating_average:null,rating_count:0};
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>emptyProfile} as Response)));
    render(<ProfilePage own authenticated viewerPersonId="person-1" onLogin={()=>{}}/>);
    const heading=await screen.findByRole('heading',{name:'Avaliações'});
    const ratings=within(heading.closest('section')!);
    expect(ratings.getByText('Nenhuma avaliação')).toBeTruthy();
    expect(ratings.queryByRole('group',{name:'Sua avaliação'})).toBeNull();
    expect(ratings.queryByText('Você não pode avaliar o próprio perfil.')).toBeNull();
  });

  it('mostra somente a média e contagem no perfil próprio com notas',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>profile} as Response)));
    render(<ProfilePage own authenticated viewerPersonId="person-1" onLogin={()=>{}}/>);
    const heading=await screen.findByRole('heading',{name:'Avaliações'});
    const ratings=within(heading.closest('section')!);
    expect(ratings.getByText('Média 4.3 de 5')).toBeTruthy();
    expect(ratings.getByText('3 avaliações')).toBeTruthy();
    expect(ratings.getByLabelText('Média 4.3 de 5')).toBeTruthy();
    expect(ratings.queryByRole('group',{name:'Sua avaliação'})).toBeNull();
  });

  it('trata o perfil aberto pela URL pública como próprio quando o id coincide',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...profile,rating_count:1})} as Response)));
    render(<ProfilePage id="person-1" authenticated={false} viewerPersonId="person-1" onLogin={()=>{}}/>);
    const heading=await screen.findByRole('heading',{name:'Avaliações'});
    const ratings=within(heading.closest('section')!);
    expect(ratings.getByText('Média 4.3 de 5')).toBeTruthy();
    expect(ratings.getByText('1 avaliação')).toBeTruthy();
    expect(ratings.queryByRole('group',{name:'Sua avaliação'})).toBeNull();
  });

  it('mantém apelidos e habilidades nulas como dados opcionais no formulário próprio',async()=>{
    const calls:Array<{url:string;init:RequestInit}> = [];
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init:RequestInit={})=>{calls.push({url:String(input),init});return {ok:true,json:async()=>profile} as Response;}));
    render(<ProfilePage own authenticated viewerUid="uid-1" onLogin={()=>{}}/>);
    fireEvent.click(await screen.findByRole('button',{name:'Editar perfil'}));
    await waitFor(()=>expect(screen.getByRole('heading',{name:'Editar perfil'})).toBeTruthy());
    expect((screen.getByLabelText(/Apelidos para apresentação/i) as HTMLTextAreaElement).value).toBe('Aninha');
    expect(screen.getByText('Informar minhas habilidades')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Salvar perfil'}));
    await waitFor(()=>expect(calls.some(call=>call.url==='/api/me/profile'&&call.init.method==='PATCH')).toBe(true));
    const patch=calls.find(call=>call.url==='/api/me/profile'&&call.init.method==='PATCH')!;
    expect(new Headers(patch.init.headers).get('X-Fred-Account')).toBe('uid-1');
    expect(JSON.parse(String(patch.init.body))).not.toHaveProperty('name');
  });

  it('envia apenas os campos permitidos ao salvar uma avaliação',async()=>{
    const calls:Array<{url:string;init:RequestInit}> = [];
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init:RequestInit={})=>{const url=String(input);calls.push({url,init});return {ok:true,json:async()=>url.includes('/ratings/')?{stars:2,publish_identity:false,rating_average:4.3,rating_count:3}:profile} as Response;}));
    render(<ProfilePage id="person-1" authenticated viewerUid="uid-1" viewerPersonId="person-2" onLogin={()=>{}}/>);
    fireEvent.click(await screen.findByRole('button',{name:'4 estrelas'}));
    await waitFor(()=>expect(calls.some(call=>call.url==='/api/me/ratings/person-1'&&call.init.method==='PUT')).toBe(true));
    const put=calls.find(call=>call.url==='/api/me/ratings/person-1'&&call.init.method==='PUT')!;
    expect(JSON.parse(String(put.init.body))).toEqual({stars:4,publish_identity:false});
    expect(new Headers(put.init.headers).get('X-Fred-Account')).toBe('uid-1');
  });

  it('preserves auth account header and browser multipart boundary',async()=>{
    let options:RequestInit|undefined;
    vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init:RequestInit={})=>{options=init;return {ok:true,json:async()=>({ok:true})} as Response;}));
    const body=new FormData();body.append('file',new File(['photo'],'photo.png',{type:'image/png'}));body.append('crop','{}');
    await request('/api/me/profile/photo',{method:'POST',body},'uid-1');
    expect(new Headers(options?.headers).get('X-Fred-Account')).toBe('uid-1');
    expect(new Headers(options?.headers).has('Content-Type')).toBe(false);
  });
});
