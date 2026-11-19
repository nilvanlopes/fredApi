import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import HoloCard from './HoloCard';

const frames = new Map<number, FrameRequestCallback>();
let nextFrame = 0;
let devicePixelRatioDescriptor: PropertyDescriptor | undefined;
let documentHiddenDescriptor: PropertyDescriptor | undefined;

class TestResizeObserver {
  observe(target: Element) {
    Object.defineProperty(target, 'clientWidth', { configurable: true, value: 120 });
    Object.defineProperty(target, 'clientHeight', { configurable: true, value: 60 });
  }
  unobserve() {}
  disconnect() {}
}
class TestIntersectionObserver {
  constructor(private callback: (entries: Array<{ isIntersecting: boolean }>) => void) {}
  observe() { this.callback([{ isIntersecting: true }]); }
  unobserve() {}
  disconnect() {}
}

class TestPointerEvent extends MouseEvent {
  readonly pointerType: string;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerType = init.pointerType ?? 'mouse';
  }
}

function flushFrame(timestamp: number) {
  const pending = [...frames.values()];
  frames.clear();
  act(() => pending.forEach(callback => callback(timestamp)));
}

function settleFrames(start: number, interval = 20, limit = 90) {
  let timestamp = start;
  for (let i = 0; i < limit && frames.size; i++, timestamp += interval) flushFrame(timestamp);
  return timestamp;
}

beforeEach(() => {
  frames.clear();
  nextFrame = 0;
  devicePixelRatioDescriptor = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio');
  documentHiddenDescriptor = Object.getOwnPropertyDescriptor(document, 'hidden');
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 3 });
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++nextFrame;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { frames.delete(id); });
  vi.stubGlobal('ResizeObserver', TestResizeObserver);
  vi.stubGlobal('IntersectionObserver', TestIntersectionObserver);
  vi.stubGlobal('PointerEvent', TestPointerEvent);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => null);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (devicePixelRatioDescriptor) Object.defineProperty(window, 'devicePixelRatio', devicePixelRatioDescriptor);
  else Reflect.deleteProperty(window, 'devicePixelRatio');
  if (documentHiddenDescriptor) Object.defineProperty(document, 'hidden', documentHiddenDescriptor);
  else Reflect.deleteProperty(document, 'hidden');
});

describe('HoloCard rendering budget', () => {
  it('caps backing pixels and skips animation updates above maxFps', () => {
    const { container } = render(<HoloCard maxDpr={1} maxFps={30} />);
    const canvas = container.querySelector('canvas')!;
    const rotor = container.querySelector<HTMLElement>('.holo-card__rotor')!;
    expect(canvas.width).toBe(120);
    expect(canvas.height).toBe(60);

    const start = performance.now() + 100;
    flushFrame(start);
    const firstTransform = rotor.style.transform;
    const root = container.querySelector<HTMLElement>('.holo-card')!;
    const firstLight = root.style.getPropertyValue('--hc-light-x');
    expect(firstLight).not.toBe('');
    flushFrame(start + 16);
    expect(rotor.style.transform).toBe(firstTransform);
    expect(root.style.getPropertyValue('--hc-light-x')).toBe(firstLight);
    flushFrame(start + 34);
    expect(rotor.style.transform).not.toBe(firstTransform);
    expect(root.style.getPropertyValue('--hc-light-x')).not.toBe(firstLight);
  });

  it('stops RAF after settling and wakes again when the pointer moves', () => {
    const { container } = render(<HoloCard idle={false} />);
    const root = container.querySelector<HTMLElement>('.holo-card')!;
    const rotor = container.querySelector<HTMLElement>('.holo-card__rotor')!;
    vi.spyOn(root, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 120, bottom: 60, width: 120, height: 60,
      toJSON: () => ({}),
    });
    const settledAt = settleFrames(performance.now() + 20);
    expect(frames.size).toBe(0);

    const settledTransform = rotor.style.transform;
    fireEvent.pointerMove(root, { pointerType: 'mouse', clientX: 108, clientY: 8 });
    expect(frames.size).toBe(1);
    flushFrame(settledAt + 20);
    expect(rotor.style.transform).not.toBe(settledTransform);
    expect(frames.size).toBe(1);

    fireEvent.pointerLeave(root);
    settleFrames(settledAt + 40);
    expect(frames.size).toBe(0);
  });

  it('pauses while the document is hidden and resumes when visible', () => {
    render(<HoloCard />);
    expect(frames.size).toBe(1);
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    expect(frames.size).toBe(0);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    expect(frames.size).toBe(1);
  });
});
