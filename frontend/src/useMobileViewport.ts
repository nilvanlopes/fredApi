import { useSyncExternalStore } from 'react';

const mediaQuery = '(max-width: 760px)';
type Listener = () => void;

let source: typeof window.matchMedia | undefined;
let media: MediaQueryList | null = null;
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach(listener => listener());
}

function getMedia() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  if (!media || source !== window.matchMedia) {
    if (media && listeners.size) media.removeEventListener('change', notify);
    source = window.matchMedia;
    media = window.matchMedia(mediaQuery);
    if (listeners.size) media.addEventListener('change', notify);
  }
  return media;
}

function getSnapshot() {
  return getMedia()?.matches ?? false;
}

function subscribe(listener: Listener) {
  const query = getMedia();
  if (!query) return () => {};
  listeners.add(listener);
  if (listeners.size === 1) query.addEventListener('change', notify);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) query.removeEventListener('change', notify);
  };
}

export function useMobileViewport() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
