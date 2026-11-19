import { useEffect, useState } from 'react';
import { CalendarDays, CreditCard, Ellipsis, History, LayoutDashboard, LogOut, UserRound, Users, Wallet, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import type { User } from './api';
import { ReadModal } from './ui';
import { useMobileViewport } from './useMobileViewport';
import GlassSurface from './components/GlassSurface';
import './MobileNavigation.css';

type Page = 'overview' | 'monthly' | 'games' | 'charges' | 'people' | 'accounts' | 'audit' | 'player' | 'player-games' | 'player-monthly' | 'player-finance';

type Props = {
  page: Page;
  hashRoute: string;
  isPlayerView: boolean;
  user: User;
  canSwitchProfile: boolean;
  logoutUrl: string;
  onNavigate: (page: Page) => void;
  onProfile: () => void;
  onSwitchProfile: () => void;
};

type Destination = { id: Page | 'more' | 'profile'; label: string; icon: typeof LayoutDashboard };

function Action({ item, active, onClick, children }: { item: Destination; active: boolean; onClick: () => void; children?: ReactNode }) {
  const Icon = item.icon;
  return <button className={`mobile-navigation__action${active ? ' is-active' : ''}`} type="button" aria-current={active ? 'page' : undefined} onClick={onClick}>
    <Icon size={19} strokeWidth={1.9}/><span>{item.label}</span>{children}
  </button>;
}

export default function MobileNavigation({ page, hashRoute, isPlayerView, user, canSwitchProfile, logoutUrl, onNavigate, onProfile, onSwitchProfile }: Props) {
  const mobile = useMobileViewport();
  const [sheetOpen, setSheetOpen] = useState(false);
  useEffect(() => { setSheetOpen(false); }, [page, hashRoute]);
  if (!mobile) return null;

  const base: Destination[] = isPlayerView
    ? [
      { id: 'player', label: 'Início', icon: LayoutDashboard },
      { id: 'player-games', label: 'Partidas', icon: CalendarDays },
      { id: 'player-monthly', label: 'Assinantes', icon: CreditCard },
      { id: 'player-finance', label: 'Financeiro', icon: Wallet },
      { id: 'profile', label: 'Perfil', icon: UserRound },
    ]
    : [
      { id: 'overview', label: 'Início', icon: LayoutDashboard },
      { id: 'monthly', label: 'Assinantes', icon: CreditCard },
      { id: 'games', label: 'Partidas', icon: CalendarDays },
      { id: 'charges', label: 'Financeiro', icon: Wallet },
      { id: 'more', label: 'Mais', icon: Ellipsis },
    ];
  const activeHash = hashRoute.split('?')[0] || page;
  const active = (id: Destination['id']) => id === 'profile'
    ? activeHash === 'my-profile' || activeHash.startsWith('profile/')
    : id === 'more'
      ? ['people', 'accounts', 'audit', 'my-profile'].includes(activeHash) || activeHash.startsWith('profile/')
      : activeHash === id;
  const activeIndex = Math.max(0, base.findIndex(item => active(item.id)));
  const navigate = (id: Page) => { setSheetOpen(false); onNavigate(id); };
  const showProfileSheet = () => setSheetOpen(true);

  return <>
    <div className={`mobile-navigation${isPlayerView ? ' mobile-navigation--player' : ''}`} role="navigation" aria-label="Navegação mobile">
      <GlassSurface className="mobile-navigation__glass" width="100%" height="auto" borderRadius={28} blur={12} backgroundOpacity={isPlayerView ? 0.46 : 0.28} distortionScale={-80} renderer="svg" refraction={false}>
        <div className="mobile-navigation__actions">
          {isPlayerView ? <span className="mobile-navigation__player-indicator" aria-hidden="true" style={{ transform: `translateX(${activeIndex * 100}%)` }}/> : null}
          {base.map(item => <Action key={item.id} item={item} active={active(item.id)} onClick={() => {
            if (item.id === 'more' || item.id === 'profile') showProfileSheet();
            else navigate(item.id);
          }}/>) }
        </div>
      </GlassSurface>
    </div>
    {sheetOpen ? <ReadModal title={isPlayerView ? 'Perfil e opções' : 'Mais opções'} onClose={() => setSheetOpen(false)}>
      <nav className="mobile-navigation__sheet" aria-label={isPlayerView ? 'Perfil e opções' : 'Mais opções'}>
        {!isPlayerView ? <>
          <button type="button" onClick={() => navigate('people')}><Users size={18}/>Jogadores</button>
          <button type="button" onClick={() => navigate('accounts')}><ShieldCheck size={18}/>Contas e acessos</button>
          <button type="button" onClick={() => navigate('audit')}><History size={18}/>Histórico de alterações</button>
        </> : null}
        {user.person_id ? <button type="button" onClick={() => { setSheetOpen(false); onProfile(); }}><UserRound size={18}/>Meu perfil</button> : null}
        {canSwitchProfile ? <button type="button" onClick={() => { setSheetOpen(false); onSwitchProfile(); }}><LayoutDashboard size={18}/>{isPlayerView ? 'Painel do manager' : 'Meu painel de jogador'}</button> : null}
        <a href={logoutUrl}><LogOut size={18}/>Sair da conta</a>
      </nav>
    </ReadModal> : null}
  </>;
}
