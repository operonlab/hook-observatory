import { describe, it, expect } from 'vitest';
import { createFSM, eventToAnim, eventToBubble, bubbleDuration, directionTo } from '../CharacterFSM';

describe('createFSM', () => {
  it('initializes with IDLE state at seat position', () => {
    const fsm = createFSM({ x: 5, y: 3 });
    expect(fsm.state).toBe('IDLE');
    expect(fsm.pos).toEqual({ x: 5, y: 3 });
    expect(fsm.seat).toEqual({ x: 5, y: 3 });
    expect(fsm.spawning).toBe(true);
  });

  it('initializes at default position when no seat', () => {
    const fsm = createFSM(null);
    expect(fsm.pos).toEqual({ x: 5, y: 5 });
    expect(fsm.seat).toBeNull();
  });
});

describe('eventToAnim', () => {
  it('maps tool_start to TYPE', () => {
    expect(eventToAnim('tool_start', 'Edit')).toBe('TYPE');
  });

  it('maps thinking to THINK', () => {
    expect(eventToAnim('thinking')).toBe('THINK');
  });

  it('maps tool_permission to WAIT', () => {
    expect(eventToAnim('tool_permission')).toBe('WAIT');
  });

  it('maps waiting to WAIT', () => {
    expect(eventToAnim('waiting')).toBe('WAIT');
  });

  it('maps idle to IDLE', () => {
    expect(eventToAnim('idle')).toBe('IDLE');
  });

  it('maps session_end to IDLE', () => {
    expect(eventToAnim('session_end')).toBe('IDLE');
  });

  it('maps message to TYPE', () => {
    expect(eventToAnim('message')).toBe('TYPE');
  });
});

describe('eventToBubble', () => {
  it('returns tool verb + detail for tool_start', () => {
    const text = eventToBubble('tool_start', 'Read', 'src/App.tsx');
    expect(text).toBe('讀取 src/App.tsx');
  });

  it('returns "需要授權！" for tool_permission', () => {
    expect(eventToBubble('tool_permission')).toBe('需要授權！');
  });

  it('returns "..." for thinking', () => {
    expect(eventToBubble('thinking')).toBe('...');
  });

  it('returns null for idle', () => {
    expect(eventToBubble('idle')).toBeNull();
  });

  it('truncates long tool input', () => {
    const text = eventToBubble('tool_start', 'Bash', 'a'.repeat(50));
    expect(text!.length).toBeLessThanOrEqual(38); // "Running " (8) + 30
  });
});

describe('bubbleDuration', () => {
  it('returns 30000 for tool_start', () => {
    expect(bubbleDuration('tool_start')).toBe(30000);
  });

  it('returns 9000 for message', () => {
    expect(bubbleDuration('message')).toBe(9000);
  });

  it('returns 0 for idle', () => {
    expect(bubbleDuration('idle')).toBe(0);
  });
});

describe('directionTo', () => {
  it('returns right when target is to the right', () => {
    expect(directionTo({ x: 0, y: 0 }, { x: 2, y: 0 })).toBe('right');
  });

  it('returns left when target is to the left', () => {
    expect(directionTo({ x: 3, y: 0 }, { x: 0, y: 0 })).toBe('left');
  });

  it('returns down when target is below', () => {
    expect(directionTo({ x: 0, y: 0 }, { x: 0, y: 3 })).toBe('down');
  });

  it('returns up when target is above', () => {
    expect(directionTo({ x: 0, y: 3 }, { x: 0, y: 0 })).toBe('up');
  });

  it('prefers horizontal when dx > dy', () => {
    expect(directionTo({ x: 0, y: 0 }, { x: 3, y: 1 })).toBe('right');
  });
});
