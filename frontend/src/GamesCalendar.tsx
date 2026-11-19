import { useId, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { Game } from './api';
import './GamesCalendar.css';

const weekdays = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
const shortWeekdays = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const dateInBrasilia = new Intl.DateTimeFormat('pt-BR', {
  timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit',
});
const monthFormat = new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC', month: 'long', year: 'numeric' });
const fullDateFormat = new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC', dateStyle: 'full' });

function todayInBrasilia() {
  const parts = dateInBrasilia.formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

const dateKey = (date: Date) => date.toISOString().slice(0, 10);
const monthStart = (month: string) => new Date(`${month}-01T00:00:00Z`);

function calendarWeeks(first: Date) {
  const last = new Date(first);
  last.setUTCMonth(last.getUTCMonth() + 1, 0);
  const offset = first.getUTCDay();
  return Array.from({ length: Math.ceil((offset + last.getUTCDate()) / 7) }, (_, week) =>
    weekdays.map((_, weekday) => {
      const day = new Date(first);
      day.setUTCDate(week * 7 + weekday - offset + 1);
      return day;
    }),
  );
}

interface GamesCalendarProps {
  games: Game[];
  selectedId?: string;
  onSelect: (id: string) => void;
}

export function GamesCalendar({ games, selectedId, onSelect }: GamesCalendarProps) {
  const titleId = useId();
  const [visibleMonth, setVisibleMonth] = useState<string | null>(null);
  const today = todayInBrasilia();
  const selectedDate = games.find(game => game.id === selectedId)?.game_date;
  const month = visibleMonth ?? (selectedDate ?? today).slice(0, 7);
  const first = monthStart(month);
  const gamesByDate = new Map(games.map(game => [game.game_date, game]));

  const move = (amount: number) => setVisibleMonth(previous => {
    const start = monthStart(previous ?? month);
    start.setUTCMonth(start.getUTCMonth() + amount);
    return dateKey(start).slice(0, 7);
  });

  return <div className="games-calendar">
    <div className="games-calendar-header">
      <h3 id={titleId} aria-live="polite">{monthFormat.format(first)}</h3>
      <div className="games-calendar-nav">
        <button className="icon-button" type="button" aria-label="Mês anterior" onClick={() => move(-1)}><ChevronLeft size={18}/></button>
        <button className="button small secondary" type="button" onClick={() => setVisibleMonth(today.slice(0, 7))}>Hoje</button>
        <button className="icon-button" type="button" aria-label="Próximo mês" onClick={() => move(1)}><ChevronRight size={18}/></button>
      </div>
    </div>
    <table aria-labelledby={titleId}>
      <thead><tr>{weekdays.map((weekday, index) =>
        <th key={weekday} scope="col" aria-label={weekday}>{shortWeekdays[index]}</th>,
      )}</tr></thead>
      <tbody>{calendarWeeks(first).map(week => <tr key={dateKey(week[0])}>{week.map(day => {
        const key = dateKey(day);
        const inMonth = key.startsWith(month);
        const game = inMonth ? gamesByDate.get(key) : undefined;
        const current = inMonth && key === today ? 'date' : undefined;
        return <td key={key}>
          {game ? <button
            className="games-calendar-day games-calendar-match"
            type="button"
            aria-label={`Abrir lista da partida de ${fullDateFormat.format(day)}`}
            aria-current={current}
            aria-pressed={game.id === selectedId}
            onClick={() => onSelect(game.id)}
          ><span>{day.getUTCDate()}</span><span className="games-calendar-dot" aria-hidden="true"/></button>
            : <span className={`games-calendar-day${inMonth ? '' : ' games-calendar-adjacent'}`} aria-current={current} aria-hidden={inMonth ? undefined : true}>{day.getUTCDate()}</span>}
        </td>;
      })}</tr>)}</tbody>
    </table>
  </div>;
}
