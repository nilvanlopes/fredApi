import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, RotateCcw } from 'lucide-react';
import { Empty } from './ui';
import './List.css';

type Value = string | number | boolean | null | undefined;
type Kind = 'text' | 'select' | 'number' | 'money' | 'date' | 'datetime';
type DateKind = 'date' | 'datetime';
type Option = { value: string; label: string };
export interface Column<T> {
  id: string;
  label: string;
  value: (item: T) => Value;
  kind?: Kind;
  options?: Option[];
  filter?: 'hidden' | 'on-click';
  filterKind?: Kind;
  filterValue?: (item: T) => Value;
  hidden?: boolean;
  render?: (item: T) => ReactNode;
}
export type Filters = Record<string, { value?: string; min?: string; max?: string }>;
export type Sort = { id: string; direction: 'asc' | 'desc' } | null;
const collator = new Intl.Collator('pt-BR', { sensitivity: 'base', numeric: true });
const formatDay = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeZone: 'America/Sao_Paulo' });
const formatDateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });
const isDate = (kind?: Kind): kind is DateKind => kind === 'date' || kind === 'datetime';
const searchable = (value: Value) => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
const numeric = (value: Value, kind: Kind) => isDate(kind) ? new Date(String(value).length === 10 ? `${value}T12:00:00-03:00` : String(value)).getTime() : Number(value);
const bound = (value: string | undefined, kind: Kind) => {
  if (!value) return null;
  if (isDate(kind)) return numeric(kind === 'datetime' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) ? `${value}:00-03:00` : value, kind);
  const number = Number(value.replace(',', '.'));
  return kind === 'money' ? Math.round(number * 100) : number;
};

function availableDates<T>(items: T[], column: Column<T>, kind: DateKind): Option[] {
  const timestamps = new Map<number, string>();
  for (const item of items) {
    const value = column.value(item);
    if (value == null || value === '') continue;
    const timestamp = numeric(value, kind);
    if (Number.isFinite(timestamp)) timestamps.set(timestamp, kind === 'date' ? String(value) : new Date(timestamp).toISOString());
  }
  const formatter = kind === 'date' ? formatDay : formatDateTime;
  return [...timestamps].sort(([a], [b]) => a - b).map(([timestamp, value]) => ({ value, label: formatter.format(timestamp) }));
}

export function filterAndSort<T>(items:T[],columns:Column<T>[],filters:Filters={},sort:Sort=null):T[]{
  const rows = items.filter(item => columns.every(column => {
    const filter = filters[column.id];
    if (!filter || column.filter === 'hidden') return true;
    const value = (column.filterValue ?? column.value)(item);
    const kind = column.filterKind ?? column.kind ?? 'text';
    if (kind === 'text') return !filter.value || searchable(value).includes(searchable(filter.value.trim()));
    if (kind === 'select') return !filter.value || String(value ?? '') === filter.value;
    const min = bound(filter.min, kind); const max = bound(filter.max, kind);
    if (min === null && max === null) return true;
    if (value === null || value === undefined || value === '') return false;
    const number = numeric(value, kind);
    return Number.isFinite(number) && (min === null || number >= min) && (max === null || number <= max);
  }));
  const column = columns.find(item => item.id === sort?.id);
  if (sort && column) rows.sort((a, b) => {
    const av = column.value(a); const bv = column.value(b);
    const aEmpty = av === null || av === undefined || av === ''; const bEmpty = bv === null || bv === undefined || bv === '';
    if (aEmpty || bEmpty) return Number(aEmpty) - Number(bEmpty);
    const result = ['number', 'money', 'date', 'datetime'].includes(column.kind ?? '') ? numeric(av, column.kind!) - numeric(bv, column.kind!) : collator.compare(String(av), String(bv));
    return (sort.direction === 'asc' ? 1 : -1) * result;
  });
  return rows;
}
function useList<T>(items: T[], columns: Column<T>[], defaultSort: Sort, defaultFilters: Filters = {}) {
  const [savedFilters, setFilters] = useState<Filters>(defaultFilters);
  const [sort, setSort] = useState<Sort>(defaultSort);
  const dateOptions = new Map<string, Option[]>();
  const filters: Filters = {};
  for (const column of columns) {
    if (column.filter === 'hidden') continue;
    const filter = savedFilters[column.id];
    const kind = column.filterKind ?? column.kind;
    if (isDate(kind)) {
      const options = availableDates(items, column, kind);
      dateOptions.set(column.id, options);
      if (filter) filters[column.id] = {
        min: options.some(option => option.value === filter.min) ? filter.min : undefined,
        max: options.some(option => option.value === filter.max) ? filter.max : undefined,
      };
    } else if (filter) {
      filters[column.id] = filter;
    }
  }
  const update = (id: string, part: 'value' | 'min' | 'max', value: string) => setFilters(previous => ({ ...previous, [id]: { ...previous[id], [part]: value } }));
  const toggle = (id: string) => setSort(previous => previous?.id === id ? previous.direction === 'asc' ? { id, direction: 'desc' } : null : { id, direction: 'asc' });
  const reset = () => { setFilters(defaultFilters); setSort(defaultSort); };
  const active = Object.values(filters).some(filter => Object.values(filter).some(Boolean));
  const rows = filterAndSort(items,columns,filters,sort);
  return { filters, dateOptions, sort, update, toggle, reset, active, rows };
}
type ListState<T> = ReturnType<typeof useList<T>>;
function Control<T>({ column, state, items, listName, focusOnReveal = false }: { column: Column<T>; state: ListState<T>; items: T[]; listName: string; focusOnReveal?: boolean }) {
  const id = useId();
  const [filterOpen, setFilterOpen] = useState(false);
  const filterContainer = useRef<HTMLDivElement>(null);
  const kind = column.filterKind ?? column.kind ?? 'text';
  const filter = state.filters[column.id] ?? {};
  const selected = state.sort?.id === column.id;
  const direction = selected ? state.sort?.direction : null;
  const onClick = column.filter === 'on-click' && (!isDate(kind) || !!state.dateOptions.get(column.id)?.length);
  const hasFilter = column.filter !== 'hidden' && (!isDate(kind) || !!state.dateOptions.get(column.id)?.length);
  useEffect(() => {
    if (!filterOpen || !focusOnReveal) return;
    filterContainer.current?.querySelector<HTMLElement>('input, select')?.focus();
  }, [filterOpen, focusOnReveal]);
  const label = `${column.label} — ${listName}`;
  const sortButton = <button className="column-sort" type="button" onClick={() => state.toggle(column.id)} aria-label={`Ordenar ${label}: ${direction === 'asc' ? 'decrescente' : direction === 'desc' ? 'ordem original' : 'crescente'}`} aria-pressed={selected}>
    {!onClick && <span>{column.label}</span>}
    {direction === 'asc' ? <ArrowUp size={13}/> : direction === 'desc' ? <ArrowDown size={13}/> : <ArrowUpDown size={13}/>}
  </button>;
  return <div className={`column-control${column.filter === 'hidden' ? ' sort-only' : ''}`}>
    {onClick ? <div className="column-heading">
      <button className="column-filter-toggle" type="button" aria-expanded={filterOpen} aria-controls={id} data-filtered={Object.values(filter).some(Boolean)} onClick={() => setFilterOpen(open => !open)}>{column.label}</button>
      {sortButton}
    </div> : sortButton}
    {hasFilter && <div id={id} ref={filterContainer} hidden={onClick && !filterOpen}>
      <FilterControl column={column} state={state} items={items} label={label} kind={kind} filter={filter}/>
    </div>}
  </div>;
}
function FilterControl<T>({ column, state, items, label, kind, filter }: { column: Column<T>; state: ListState<T>; items: T[]; label: string; kind: Kind; filter: Filters[string] }) {
  const update = (part: keyof Filters[string], value: string) => state.update(column.id, part, value);
  if (kind === 'text') return <input aria-label={`Filtrar ${label}`} value={filter.value ?? ''} onChange={event => update('value', event.target.value)} placeholder="Filtrar…" type="search"/>;
  if (kind === 'select') {
    const options = column.options ?? [...new Set(items.map(column.value).filter(value => value != null && value !== '').map(String))].sort(collator.compare).map(value => ({ value, label: value }));
    return <select aria-label={`Filtrar ${label}`} value={filter.value ?? ''} onChange={event => update('value', event.target.value)}><option value="">Todos</option>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>;
  }
  if (isDate(kind)) {
    const options = state.dateOptions.get(column.id) ?? [];
    if (!options.length) return null;
    return <div className={`column-range ${kind}`}>
      <select aria-label={`Filtrar ${label}, de`} value={filter.min ?? ''} onChange={event => update('min', event.target.value)}><option value="">De: qualquer data</option>{options.map(option => <option key={option.value} value={option.value}>De: {option.label}</option>)}</select>
      <select aria-label={`Filtrar ${label}, até`} value={filter.max ?? ''} onChange={event => update('max', event.target.value)}><option value="">Até: qualquer data</option>{options.map(option => <option key={option.value} value={option.value}>Até: {option.label}</option>)}</select>
    </div>;
  }
  return <div className={`column-range ${kind}`}>
    <input aria-label={`Filtrar ${label}, mínimo${kind === 'money' ? ' em reais' : ''}`} type="number" step={kind === 'money' ? '0.01' : undefined} placeholder={kind === 'money' ? 'R$ mín.' : 'Mín.'} value={filter.min ?? ''} onChange={event => update('min', event.target.value)}/>
    <input aria-label={`Filtrar ${label}, máximo${kind === 'money' ? ' em reais' : ''}`} type="number" step={kind === 'money' ? '0.01' : undefined} placeholder={kind === 'money' ? 'R$ máx.' : 'Máx.'} value={filter.max ?? ''} onChange={event => update('max', event.target.value)}/>
  </div>;
}
function ListSummary<T>({ state, total, name, limit, scope, layout = 'table' }: { state: ListState<T>; total: number; name: string; limit?: number; scope?: string; layout?: 'table' | 'cards' }) {
  const order = state.sort?.direction === 'asc' ? 'crescente' : state.sort?.direction === 'desc' ? 'decrescente' : 'ordem original';
  return <div className="list-summary">
    <span role="status" aria-live="polite">
      {limit && state.rows.length > limit ? `${limit} de ${state.rows.length}` : state.rows.length} de {total} registros
      {state.active ? ' · filtros aplicados' : ''}
      {layout === 'table' ? ` · ${order}` : ''}
      {scope ? ` · ${scope}` : ''}
    </span>
    {layout === 'table' && <button className="text-link" type="button" onClick={state.reset} aria-label={`Limpar filtros e ordenação — ${name}`}><RotateCcw size={12}/>Limpar</button>}
  </div>;
}
export function DataTable<T>({ name, items, columns, rowKey, rowId, actions, defaultSort = null, defaultFilters = {}, showSummary = true, showScrollHint = true, emptyTitle = 'Nenhum registro ainda', emptyMessage, footer, onRowClick, rowLabel }: { name: string; items: T[]; columns: Column<T>[]; rowKey: (item: T) => string; rowId?: (item: T) => string; actions?: (item: T) => ReactNode; defaultSort?: Sort; defaultFilters?: Filters; showSummary?: boolean; showScrollHint?: boolean; emptyTitle?: string; emptyMessage?: ReactNode; footer?: (rows: T[]) => ReactNode; onRowClick?: (item: T) => void; rowLabel?: (item: T) => string }) {
  const allColumns = columns.map(column => column.filter ? column : { ...column, filter: 'on-click' as const });
  const tableColumns = allColumns.filter(column => !column.hidden);
  const state = useList(items, allColumns, defaultSort, defaultFilters);
  const activateRow = (event: React.MouseEvent<HTMLTableRowElement> | React.KeyboardEvent<HTMLTableRowElement>, item: T) => {
    if (!onRowClick || (event.target as HTMLElement).closest('button, a, input, select, textarea, [role="button"]')) return;
    if ('key' in event && event.key !== 'Enter' && event.key !== ' ') return;
    if ('key' in event) event.preventDefault();
    onRowClick(item);
  };
  return <div className="data-list" data-list={name}>{showSummary && <ListSummary state={state} total={items.length} name={name}/>} {showScrollHint ? <p className="table-scroll-hint" aria-hidden="true">Deslize a tabela para ver todas as colunas.</p> : null}<div className="table-wrap" role="region" aria-label={`Tabela ${name}, role horizontalmente para ver todas as colunas`} tabIndex={0}><table aria-label={name}><thead><tr>{tableColumns.map(column => <th key={column.id} scope="col" aria-sort={state.sort?.id === column.id ? state.sort.direction === 'asc' ? 'ascending' : 'descending' : 'none'}><Control column={column} state={state} items={items} listName={name}/></th>)}{actions ? <th scope="col" className="align-right">Ações</th> : null}</tr></thead><tbody>{state.rows.map(item => <tr key={rowKey(item)} id={rowId?.(item)} className={onRowClick ? 'clickable-row' : undefined} tabIndex={onRowClick ? 0 : undefined} aria-label={onRowClick ? rowLabel?.(item) : undefined} onClick={onRowClick ? event => activateRow(event, item) : undefined} onKeyDown={onRowClick ? event => activateRow(event, item) : undefined}>{tableColumns.map(column => <td key={column.id} data-label={column.label}>{column.render ? column.render(item) : String(column.value(item) ?? '—')}</td>)}{actions ? <td><div className="row-actions">{actions(item)}</div></td> : null}</tr>)}</tbody></table></div>{!state.rows.length ? <Empty title={items.length ? 'Nenhum resultado para estes filtros' : emptyTitle} action={items.length ? <button className="button secondary" onClick={state.reset}>Limpar filtros</button> : undefined}>{items.length ? 'Ajuste os filtros ou limpe a seleção para ver os registros.' : emptyMessage}</Empty> : null}{footer ? <div className="list-footer">{footer(state.rows)}</div> : null}</div>;
}
export function DataCards<T>({ name, items, columns, children, limit, scope, defaultSort = null, showSummary = true, showFilters = true, emptyTitle = 'Nenhum registro ainda', emptyMessage, focusFiltersOnReveal = false }: { name: string; items: T[]; columns: Column<T>[]; children: (rows: T[]) => ReactNode; limit?: number; scope?: string; defaultSort?: Sort; showSummary?: boolean; showFilters?: boolean; emptyTitle?: string; emptyMessage?: ReactNode; focusFiltersOnReveal?: boolean }) {
  const state = useList(items, columns, defaultSort);
  const modified = state.active || state.sort?.id !== defaultSort?.id || state.sort?.direction !== defaultSort?.direction;
  const resetLabel = `Limpar filtros e ordenação — ${name}`;
  return <div className="data-list card-data-list" data-list={name}>
    {showFilters ? <div className="card-list-toolbar" role="group" aria-label={`Filtros e ordenação — ${name}`}>
      <div className="card-list-head">
        {columns.map(column => <Control key={column.id} column={column} state={state} items={items} listName={name} focusOnReveal={focusFiltersOnReveal}/>)}
      </div>
      {modified && <button className="icon-button" type="button" onClick={state.reset} aria-label={resetLabel} title={resetLabel}><RotateCcw size={15}/></button>}
    </div> : null}
    {state.rows.length ? children(limit ? state.rows.slice(0, limit) : state.rows) : <Empty title={items.length ? 'Nenhum resultado para estes filtros' : emptyTitle}>{items.length ? 'Ajuste os filtros ou limpe a seleção para ver os registros.' : emptyMessage}</Empty>}
    {showSummary && <ListSummary state={state} total={items.length} name={name} limit={limit} scope={scope} layout="cards"/>}
  </div>;
}
