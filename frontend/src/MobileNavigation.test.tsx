import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from './api';
import type { ReactNode } from 'react';
import MobileNavigation from './MobileNavigation';

// Navigation unit tests do not emulate the vendor renderer's canvas/ResizeObserver.
vi.mock('./components/GlassSurface', () => ({
  default: ({ children, className }: { children:ReactNode; className?:string }) => <div className={className}>{children}</div>,
}));

const manager: User = { uid: 'manager', username: 'gestor', name: 'Gestor', email: '', is_admin: true };
const player: User = { uid: 'player', username: 'jogador', name: 'Jogador', email: '', is_admin: false, person_id: 'person-1' };

function setMobile(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches,
    media: '(max-width: 760px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

function renderNavigation({
  user = manager,
  page = 'overview',
  hashRoute = 'overview',
  isPlayerView = false,
  canSwitchProfile = false,
}: {
  user?: User;
  page?: 'overview' | 'monthly' | 'games' | 'charges' | 'people' | 'accounts' | 'audit' | 'player' | 'player-games' | 'player-monthly' | 'player-finance';
  hashRoute?: string;
  isPlayerView?: boolean;
  canSwitchProfile?: boolean;
} = {}) {
  const onNavigate = vi.fn();
  const onProfile = vi.fn();
  const onSwitchProfile = vi.fn();
  render(<MobileNavigation page={page} hashRoute={hashRoute} isPlayerView={isPlayerView} user={user} canSwitchProfile={canSwitchProfile} logoutUrl="/api/auth/logout?next=%2F" onNavigate={onNavigate} onProfile={onProfile} onSwitchProfile={onSwitchProfile}/>);
  return { onNavigate, onProfile, onSwitchProfile };
}

describe('navegação mobile', () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it('não renderiza quando matchMedia não existe ou indica desktop', () => {
    renderNavigation();
    expect(screen.queryByRole('navigation', { name: 'Navegação mobile' })).toBeNull();
    setMobile(false);
    renderNavigation();
    expect(screen.queryByRole('navigation', { name: 'Navegação mobile' })).toBeNull();
  });

  it('mostra os destinos principais do gestor, marca o hash ativo e abre rotas extras', () => {
    setMobile(true);
    const { onNavigate } = renderNavigation({ page: 'games', hashRoute: 'games?date=2026-11-18' });
    expect(screen.getByRole('button', { name: 'Partidas' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: 'Mais' }));
    expect(screen.getByRole('dialog', { name: 'Mais opções' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Jogadores' }));
    expect(onNavigate).toHaveBeenCalledWith('people');
    expect(screen.queryByRole('dialog', { name: 'Mais opções' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Mais' }));
    fireEvent.click(screen.getByRole('button', { name: 'Contas e acessos' }));
    expect(onNavigate).toHaveBeenCalledWith('accounts');
    fireEvent.click(screen.getByRole('button', { name: 'Mais' }));
    fireEvent.click(screen.getByRole('button', { name: 'Histórico de alterações' }));
    expect(onNavigate).toHaveBeenCalledWith('audit');
  });

  it('oferece perfil, alternância permitida e logout no menu do jogador', () => {
    setMobile(true);
    const { onProfile, onSwitchProfile } = renderNavigation({ user: { ...player, is_admin: true }, page: 'player-games', hashRoute: 'player-games', isPlayerView: true, canSwitchProfile: true });
    fireEvent.click(screen.getByRole('button', { name: 'Perfil' }));
    expect(screen.getByRole('dialog', { name: 'Perfil e opções' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Meu perfil' }));
    expect(onProfile).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Perfil' }));
    fireEvent.click(screen.getByRole('button', { name: 'Painel do manager' }));
    expect(onSwitchProfile).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Perfil' }));
    expect(screen.getByRole('link', { name: 'Sair da conta' }).getAttribute('href')).toBe('/api/auth/logout?next=%2F');
  });

  it('mantém a tela inicial do jogador como destino ativo', () => {
    setMobile(true);
    renderNavigation({ user: player, page: 'player', hashRoute: 'player', isPlayerView: true });
    expect(screen.getByRole('button', { name: 'Início' }).getAttribute('aria-current')).toBe('page');
    expect(screen.queryByRole('button', { name: 'Mais' })).toBeNull();
  });

  it('move o estado selecionado do dock do jogador junto com a rota', () => {
    setMobile(true);
    const props = { page: 'player' as const, hashRoute: 'player', isPlayerView: true, user: player, canSwitchProfile: false, logoutUrl: '/logout', onNavigate: vi.fn(), onProfile: vi.fn(), onSwitchProfile: vi.fn() };
    const { rerender, container } = render(<MobileNavigation {...props}/>);
    expect(screen.getByRole('button', { name: 'Início' }).getAttribute('aria-current')).toBe('page');
    rerender(<MobileNavigation {...props} page="player-games" hashRoute="player-games"/>);
    expect(screen.getByRole('button', { name: 'Partidas' }).getAttribute('aria-current')).toBe('page');
    expect(container.querySelector('.mobile-navigation__player-indicator')?.getAttribute('style')).toContain('translateX(100%)');
  });

  it('mantém navegação para usuário autenticado na visualização de perfil público', () => {
    setMobile(true);
    renderNavigation({ hashRoute: 'profile/person-1' });
    expect(screen.getByRole('navigation', { name: 'Navegação mobile' })).toBeTruthy();
  });
});
