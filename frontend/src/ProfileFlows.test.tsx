import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ProfilePage, ProfileQuickCard } from './Profile';

const profile = {
  person_id: 'target-1', name: 'Ana Lima', nicknames: ['Aninha'], bio: '',
  positions: [], primary_position: null, sex: null, handedness: null, skills: null,
  avatar_url: null, rating_average: 4.2, rating_count: 7, games_count: 19,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('profile flows', () => {
  it('updates the viewer rating for the same profile using only rating fields', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      calls.push({ url, init });
      const body = url.includes('/api/me/ratings/')
        ? init.method === 'PUT'
          ? { stars: 4, publish_identity: true, rating_average: 4.4, rating_count: 8 }
          : { stars: 2, publish_identity: true, rating_average: 4.2, rating_count: 7 }
        : profile;
      return { ok: true, json: async () => body } as Response;
    }));

    render(<ProfilePage id="target-1" authenticated viewerUid="viewer-uid" viewerPersonId="viewer-person" onLogin={() => {}}/>);
    expect(await screen.findByRole('button', { name: '2 estrelas' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '4 estrelas' }));

    await waitFor(() => expect(calls.some(call => call.url === '/api/me/ratings/target-1' && call.init.method === 'PUT')).toBe(true));
    const get = calls.find(call => call.url === '/api/me/ratings/target-1' && !call.init.method);
    const put = calls.find(call => call.url === '/api/me/ratings/target-1' && call.init.method === 'PUT')!;
    expect(get).toBeTruthy();
    expect(JSON.parse(String(put.init.body))).toEqual({ stars: 4, publish_identity: true });
    expect(JSON.parse(String(put.init.body))).not.toHaveProperty('id');
    expect(new Headers(put.init.headers).get('X-Fred-Account')).toBe('viewer-uid');
  });

  it('saves own nicknames, bio and self-declared skills with the viewer account header', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      calls.push({ url, init });
      return { ok: true, json: async () => profile } as Response;
    }));

    render(<ProfilePage own authenticated viewerUid="owner-uid" viewerPersonId="target-1" onLogin={() => {}}/>);
    fireEvent.click(await screen.findByRole('button', { name: 'Editar perfil' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Editar perfil' }));
    fireEvent.change(dialog.getByLabelText('Apelidos para apresentação'), { target: { value: 'Aninha\nNina' } });
    fireEvent.change(dialog.getByLabelText(/Frase do perfil/), { target: { value: 'Defesa e saque.' } });
    fireEvent.click(dialog.getByLabelText('Informar minhas habilidades'));
    fireEvent.change(dialog.getByRole('slider', { name: 'Passe (0–100)' }), { target: { value: '82' } });
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar perfil' }));

    await waitFor(() => expect(calls.some(call => call.url === '/api/me/profile' && call.init.method === 'PATCH')).toBe(true));
    const patch = calls.find(call => call.url === '/api/me/profile' && call.init.method === 'PATCH')!;
    expect(new Headers(patch.init.headers).get('X-Fred-Account')).toBe('owner-uid');
    expect(JSON.parse(String(patch.init.body))).toMatchObject({
      nicknames: ['Aninha', 'Nina'], bio: 'Defesa e saque.',
      skills: { passe: 82, ataque: 50, defesa: 50, bloqueio: 50, saque: 50 },
    });
  });

  it('keeps the quick card limited to its summary and closes on request', async () => {
    const onClose = vi.fn();
    const onView = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        ...profile, bio: 'Informação completa', positions: ['ponta'], avatar_url: '/avatar.webp',
        rating_average: 4.8, rating_count: 99, games_count: 23,
      }),
    } as Response)));

    render(<ProfileQuickCard id="target-1" name="Ana Lima" onClose={onClose} onView={onView}/>);
    const dialog = within(await screen.findByRole('dialog', { name: 'Perfil resumido de Ana Lima' }));
    expect(dialog.getByText('Ana Lima')).toBeTruthy();
    expect(await dialog.findByText('4,8')).toBeTruthy();
    expect(dialog.getByText('23 partidas')).toBeTruthy();
    expect(dialog.getByRole('button', { name: 'Ver perfil' })).toBeTruthy();
    expect(dialog.queryByRole('button', { name: 'Fechar perfil' })).toBeNull();
    expect(dialog.queryByText('Informação completa')).toBeNull();
    expect(dialog.queryByText('Ponta')).toBeNull();
    expect(dialog.queryByText('99')).toBeNull();
    const avatar = screen.getByRole('dialog', { name: 'Perfil resumido de Ana Lima' }).querySelector('.profile-quick-avatar img');
    expect(avatar?.getAttribute('src')).toBe('/avatar.webp');

    fireEvent.click(dialog.getByRole('button', { name: 'Ver perfil' }));
    expect(onView).toHaveBeenCalledWith('target-1');
    fireEvent.pointerDown(document.body);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
