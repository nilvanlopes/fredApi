import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Game } from './api';
import { GamesCalendar } from './GamesCalendar';

const game = (id: string, day: string): Game => ({
  id, game_date: day, capacity: 24, cutoff_at: `${day}T16:00:00-03:00`,
  starts_at: `${day}T19:30:00-03:00`, main_count: 0, waiting_count: 0,
});

describe('calendário de partidas', () => {
  afterEach(() => vi.useRealTimers());

  it('marca os dias com partida e abre a lista da partida escolhida', () => {
    const onSelect = vi.fn();
    const games = [game('primeira', '2026-12-02'), game('segunda', '2026-12-09')];
    const { container } = render(<GamesCalendar games={games} selectedId="primeira" onSelect={onSelect}/>);

    expect(screen.getByRole('table', { name: 'dezembro de 2026' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /2 de dezembro de 2026/ }).getAttribute('aria-pressed')).toBe('true');
    expect(container.querySelectorAll('.games-calendar-dot')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /3 de dezembro de 2026/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /9 de dezembro de 2026/ }));
    expect(onSelect).toHaveBeenCalledWith('segunda');
  });

  it('navega pela virada de ano e volta para o mês atual em Brasília', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2027-01-01T01:00:00Z'));
    const games = [game('última', '2026-12-30'), game('primeira', '2027-01-06')];
    const onSelect = vi.fn();
    const { container } = render(<GamesCalendar games={games} selectedId="última" onSelect={onSelect}/>);

    fireEvent.click(screen.getByRole('button', { name: 'Próximo mês' }));
    expect(screen.getByRole('table', { name: 'janeiro de 2027' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /6 de janeiro de 2027/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /30 de dezembro de 2026/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Mês anterior' }));
    expect(screen.getByRole('table', { name: 'dezembro de 2026' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Próximo mês' }));
    fireEvent.click(screen.getByRole('button', { name: 'Hoje' }));
    expect(screen.getByRole('table', { name: 'dezembro de 2026' })).toBeTruthy();
    expect(container.querySelector('[aria-current="date"]')?.textContent).toBe('31');
    expect(onSelect).not.toHaveBeenCalled();
  });
});
