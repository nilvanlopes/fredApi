import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ProfilePage } from './Profile';

// Layout is jsdom's boundary; exercise the upload with an explicit crop result.
vi.mock('react-easy-crop', () => ({
  default: ({ onCropComplete }: { onCropComplete: (area: unknown, pixels: { x:number; y:number; width:number; height:number }) => void }) =>
    <button onClick={() => onCropComplete(null, { x:0, y:0, width:60, height:60 })}>Confirmar enquadramento</button>,
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ownerProfile = {
  person_id:'owner', name:'Ana', nicknames:[], bio:'', positions:[], primary_position:null,
  sex:null, handedness:null, skills:null, avatar_url:null, rating_average:null,
  rating_count:0, games_count:0,
};

function mockProfileApi() {
  const updated = { ...ownerProfile, avatar_url:'/api/public/profiles/owner/avatar?v=new' };
  const calls:Array<{path:string; init:RequestInit}> = [];
  let uploaded = false;
  const NativeURL = URL;
  class BlobURL extends NativeURL {
    static createObjectURL() { return 'blob:photo-preview'; }
    static revokeObjectURL = vi.fn();
  }
  vi.stubGlobal('URL', BlobURL);
  vi.stubGlobal('fetch', vi.fn(async (path:RequestInfo|URL, init:RequestInit={}) => {
    const value = String(path);
    calls.push({ path:value, init });
    if (value.endsWith('/photo/source')) return { ok:false, status:404 } as Response;
    if (init.method === 'POST') uploaded = true;
    return { ok:true, json:async () => uploaded ? updated : ownerProfile } as Response;
  }));
  return { calls, updated };
}

function renderOwnProfile(onSaved=vi.fn()) {
  render(<ProfilePage own authenticated viewerPersonId="owner" viewerUid="account-uid" onLogin={() => {}} onSaved={onSaved}/>);
  return onSaved;
}

it('uploads the crop with the current account and notifies the shell to refresh its avatar', async () => {
  const { calls, updated } = mockProfileApi();
  const onSaved = vi.fn();
  renderOwnProfile(onSaved);
  fireEvent.click(await screen.findByRole('button', { name:'Editar foto' }));
  const image = new File(['photo'], 'photo.png', { type:'image/png' });
  fireEvent.change(screen.getByLabelText('Selecionar foto do perfil'), { target:{ files:[image] } });
  fireEvent.click(await screen.findByRole('button', { name:'Confirmar enquadramento' }));
  fireEvent.click(screen.getByRole('button', { name:'Salvar foto' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));
  const upload = calls.find(call => call.path === '/api/me/profile/photo' && call.init.method === 'POST')!;
  expect(new Headers(upload.init.headers).get('X-Fred-Account')).toBe('account-uid');
  expect(new Headers(upload.init.headers).has('Content-Type')).toBe(false);
  const multipart = upload.init.body as FormData;
  expect(multipart.get('file')).toBe(image);
  expect(JSON.parse(String(multipart.get('crop')))).toEqual({ x:0, y:0, width:60, height:60 });
});

it('shows the empty photo state with one close control and disabled save', async () => {
  mockProfileApi();
  renderOwnProfile();
  fireEvent.click(await screen.findByRole('button', { name:'Editar foto' }));

  const dialog = await screen.findByRole('dialog', { name:'Foto do perfil' });
  expect(await screen.findByText('Adicione sua foto')).toBeTruthy();
  expect(screen.getByRole('button', { name:'Escolher foto' })).toBeTruthy();
  const fileInput = screen.getByLabelText('Selecionar foto do perfil') as HTMLInputElement;
  expect(fileInput.type).toBe('file');
  expect(fileInput.hidden).toBe(true);
  expect(within(dialog).queryByRole('slider', { name:'Zoom' })).toBeNull();
  expect(within(dialog).getAllByRole('button', { name:'Fechar' })).toHaveLength(1);
  expect(within(dialog).getByRole('button', { name:'Cancelar' })).toBeTruthy();
  expect((within(dialog).getByRole('button', { name:'Salvar foto' }) as HTMLButtonElement).disabled).toBe(true);
});

it('offers accessible zoom controls after choosing a photo without enabling save before crop confirmation', async () => {
  mockProfileApi();
  renderOwnProfile();
  fireEvent.click(await screen.findByRole('button', { name:'Editar foto' }));

  const dialog = await screen.findByRole('dialog', { name:'Foto do perfil' });
  const fileInput = screen.getByLabelText('Selecionar foto do perfil') as HTMLInputElement;
  fireEvent.change(fileInput, { target:{ files:[new File(['photo'], 'photo.png', { type:'image/png' })] } });

  expect(within(dialog).getByRole('button', { name:'Trocar foto' })).toBeTruthy();
  expect(within(dialog).getByRole('button', { name:'Remover foto' })).toBeTruthy();
  const slider = within(dialog).getByRole('slider', { name:'Zoom' }) as HTMLInputElement;
  expect(slider.value).toBe('1');
  expect((within(dialog).getByRole('button', { name:'Diminuir zoom' }) as HTMLButtonElement).disabled).toBe(true);
  expect((within(dialog).getByRole('button', { name:'Aumentar zoom' }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(within(dialog).getByRole('button', { name:'Aumentar zoom' }));
  expect(slider.value).toBe('1.1');
  fireEvent.change(slider, { target:{ value:'3' } });
  expect(slider.value).toBe('3');
  expect((within(dialog).getByRole('button', { name:'Aumentar zoom' }) as HTMLButtonElement).disabled).toBe(true);
  expect(fileInput.value).toBe('');
  expect((within(dialog).getByRole('button', { name:'Salvar foto' }) as HTMLButtonElement).disabled).toBe(true);
});
