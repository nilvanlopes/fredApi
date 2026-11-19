import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { request, type Session } from './api';
import { Brand, Field } from './ui';

const sports = ['volleyball', 'basketball', 'tennis'] as const;

function normalizeSignupUsername(name: string) {
  return name.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, '-').replace(/^[.\-_]+|[.\-_]+$/g, '').slice(0, 64);
}

export function Login({ session, onAuthenticated }: {
  session: Session;
  onAuthenticated: (session?: Session) => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [hosted, setHosted] = useState(false);
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [signupSent, setSignupSent] = useState(false);
  const [showSignupPassword, setShowSignupPassword] = useState(false);
  const [showSignupPasswordRepeat, setShowSignupPasswordRepeat] = useState(false);
  const [signupName, setSignupName] = useState('');
  const [usernameAvailability, setUsernameAvailability] = useState<'idle' | 'checking' | 'available' | 'taken' | 'error'>('idle');
  const usernameCheckVersion = useRef(0);
  const loginUrl = session.login_url || '/api/auth/login';
  const signupUrl = session.signup_url || '/api/auth/signup';
  const normalizedSignupUsername = normalizeSignupUsername(signupName);

  useEffect(() => {
    if (!creatingAccount || signupSent) return;
    if (!/^[A-Za-z0-9_.-]{3,64}$/.test(normalizedSignupUsername)) {
      setUsernameAvailability('idle');
      return;
    }

    const controller = new AbortController();
    const version = ++usernameCheckVersion.current;
    const timeout = window.setTimeout(() => {
      setUsernameAvailability('checking');
      request<{ username: string; available: boolean }>('/api/auth/username-availability', {
        method: 'POST',
        body: JSON.stringify({ name: signupName }),
        signal: controller.signal,
      }).then(result => {
        if (usernameCheckVersion.current === version && result.username === normalizedSignupUsername) {
          setUsernameAvailability(result.available ? 'available' : 'taken');
        }
      }).catch(() => {
        if (usernameCheckVersion.current === version) setUsernameAvailability('error');
      });
    }, 450);

    return () => {
      usernameCheckVersion.current += 1;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [creatingAccount, signupSent, signupName, normalizedSignupUsername]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setPending(true);
    setError('');
    setHosted(false);
    try {
      const result = await request<{ status: 'authenticated' | 'hosted_login_required'; session?: Session }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          identifier: fields.get('identifier'),
          password: fields.get('password'),
        }),
      });
      form.reset();
      if (result.status === 'hosted_login_required') {
        setHosted(true);
      } else if (result.status === 'authenticated') {
        onAuthenticated(result.session);
      } else {
        setError('Não foi possível entrar. Tente novamente.');
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível entrar. Tente novamente.');
    } finally {
      setPending(false);
    }
  }

  async function submitSignup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const password = String(fields.get('signup-password') ?? '');
    const passwordRepeat = String(fields.get('signup-password-repeat') ?? '');
    if (password !== passwordRepeat) {
      setError('As senhas não conferem.');
      return;
    }

    setPending(true);
    setError('');
    try {
      const result = await request<{ status: 'confirmation_sent' }>(signupUrl, {
        method: 'POST',
        body: JSON.stringify({
          name: fields.get('name'),
          email: fields.get('email'),
          password,
          password_repeat: passwordRepeat,
        }),
      });
      if (result?.status !== 'confirmation_sent') {
        throw new Error('Não foi possível confirmar o envio do email. Tente novamente.');
      }
      form.reset();
      setSignupName('');
      setSignupSent(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível criar a conta. Tente novamente.');
    } finally {
      setPending(false);
    }
  }

  function showLogin() {
    setCreatingAccount(false);
    setSignupSent(false);
    setError('');
  }

  return (
    <div className="login-shell">
      <section className="login-story">
        <Brand light/>
        <div className="login-story-copy">
          <h1>O jogo é de todos.<br/><em>A organização<br/>é com o Fred.</em></h1>
        </div>
        <div className="court-art" aria-hidden="true"><div/></div>
        <div className="sports-patterns" aria-hidden="true">
          {sports.map(sport => (
            <img key={sport} className={`sport-pattern sport-${sport}`} src={`/sports/${sport}.svg`} alt=""/>
          ))}
        </div>
      </section>
      <main className="login-form-area">
        <div className="login-mobile-brand"><Brand/></div>
        <div className="login-card">
          <h2>{creatingAccount ? 'Crie sua conta.' : 'Bom ter você por aqui.'}</h2>
          <p>{creatingAccount ? 'Cadastre-se para acompanhar suas partidas e pagamentos.' : 'Entre para acompanhar suas partidas e pagamentos.'}</p>
          {signupSent ? (
            <div className="success-message" role="status">
              <ShieldCheck size={28}/>
              <p>Enviamos um email para confirmar seu cadastro. Depois da confirmação, você já poderá entrar no Fred.</p>
              <button type="button" className="text-link" onClick={showLogin}>Voltar para entrar</button>
            </div>
          ) : creatingAccount ? (
            <form className="form-stack" method="post" action={signupUrl} onSubmit={submitSignup} aria-label="Criar conta no Fred">
              <div className="field">
                <label htmlFor="signup-name">Nome</label>
                <input id="signup-name" name="name" type="text" autoComplete="name" minLength={3} maxLength={150} value={signupName} onChange={event => { usernameCheckVersion.current += 1; setSignupName(event.target.value); setUsernameAvailability('idle'); }} required/>
                {usernameAvailability === 'checking' ? <small className="username-checking" role="status" aria-live="polite">Verificando nome de usuário…</small> : null}
                {usernameAvailability === 'available' ? <small className="username-available" role="status" aria-live="polite">Nome de usuário disponível.</small> : null}
                {usernameAvailability === 'taken' ? <small className="username-taken" role="status" aria-live="polite">Esse nome de usuário já existe. Escolha outro.</small> : null}
                {usernameAvailability === 'error' ? <small className="username-checking" role="status" aria-live="polite">Não foi possível verificar agora. Você ainda pode tentar criar a conta.</small> : null}
              </div>
              <Field label="Email">
                <input name="email" type="email" autoComplete="email" maxLength={254} required/>
              </Field>
              <div className="field">
                <label htmlFor="signup-password">Senha</label>
                <div className="password-input-wrap">
                  <input id="signup-password" name="signup-password" type={showSignupPassword ? 'text' : 'password'} autoComplete="new-password" minLength={10} maxLength={256} required/>
                  <button type="button" className="password-visibility" aria-label={showSignupPassword ? 'Ocultar senha' : 'Mostrar senha'} aria-pressed={showSignupPassword} onClick={() => setShowSignupPassword(value => !value)}>
                    {showSignupPassword ? <EyeOff size={18}/> : <Eye size={18}/>}
                  </button>
                </div>
              </div>
              <div className="field">
                <label htmlFor="signup-password-repeat">Confirme a senha</label>
                <div className="password-input-wrap">
                  <input id="signup-password-repeat" name="signup-password-repeat" type={showSignupPasswordRepeat ? 'text' : 'password'} autoComplete="new-password" minLength={10} maxLength={256} required/>
                  <button type="button" className="password-visibility" aria-label={showSignupPasswordRepeat ? 'Ocultar confirmação de senha' : 'Mostrar confirmação de senha'} aria-pressed={showSignupPasswordRepeat} onClick={() => setShowSignupPasswordRepeat(value => !value)}>
                    {showSignupPasswordRepeat ? <EyeOff size={18}/> : <Eye size={18}/>}
                  </button>
                </div>
              </div>
              {error ? <p className="form-error" role="alert">{error}</p> : null}
              <button type="submit" className="button wide" disabled={pending || usernameAvailability === 'checking' || usernameAvailability === 'taken'}>
                {pending ? 'Criando conta…' : 'Criar conta'}
              </button>
              <p className="signup-switch">
                Já possui conta?{' '}<button type="button" disabled={pending} onClick={showLogin}>Fazer login</button>
              </p>
            </form>
          ) : (
          <form className="form-stack" method="post" action="/api/auth/login" onSubmit={submit} aria-label="Entrar no Fred">
            <Field label="Email ou usuário">
              <input name="identifier" type="text" autoComplete="username" maxLength={254} required/>
            </Field>
            <Field label="Senha">
              <input name="password" type="password" autoComplete="current-password" maxLength={1024} required/>
            </Field>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            {hosted ? (
              <p className="login-hosted" role="status">
                Conclua a verificação na <a href={loginUrl}>página segura de login</a>.
              </p>
            ) : null}
            <button type="submit" className="button wide" disabled={pending}>
              {pending ? 'Entrando…' : 'Entrar'}
            </button>
            <p className="signup-switch">
              Ainda não tem conta?{' '}<button type="button" disabled={pending} onClick={() => {
                setCreatingAccount(true);
                setError('');
                setHosted(false);
              }}>Criar conta</button>
            </p>
          </form>
          )}
          <div className="or"><span/>ou<span/></div>
          <a className="button google wide" href={session.google_login_url || '/api/auth/google'}>
            <svg width="19" height="19" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.73-.06-1.42-.19-2.09H12v3.96h5.92a5.07 5.07 0 0 1-2.2 3.32v2.76h3.56c2.08-1.92 3.28-4.75 3.28-7.95Z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.56-2.76c-.98.66-2.24 1.06-3.72 1.06-2.86 0-5.29-1.94-6.16-4.54H2.17v2.84A11 11 0 0 0 12 23Z"/>
              <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.17v2.84a11 11 0 0 0 0 9.88l3.67-2.84Z"/>
              <path fill="#EA4335" d="M12 5.36c1.62 0 3.06.56 4.21 1.64l3.16-3.16A10.57 10.57 0 0 0 12 1a11 11 0 0 0-9.83 6.06L5.84 9.9C6.71 7.3 9.14 5.36 12 5.36Z"/>
            </svg>
            Continuar com Google
          </a>
          <div className="secure-note"><ShieldCheck size={17}/><span>Acesso protegido</span></div>
        </div>
      </main>
    </div>
  );
}
