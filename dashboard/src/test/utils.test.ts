import { describe, it, expect } from 'vitest';
import { cn } from '../lib/utils';

describe('cn()', () => {
  it('joins string class names', () => {
    expect(cn('text-sm', 'font-bold')).toBe('text-sm font-bold');
  });

  it('skips falsy values', () => {
    expect(cn('base', false && 'hidden', null, undefined, '')).toBe('base');
  });

  it('resolves conflicting Tailwind classes using the last one', () => {
    // tailwind-merge should collapse these to text-lg
    expect(cn('text-sm', 'text-lg')).toBe('text-lg');
  });

  it('accepts an array of class names', () => {
    expect(cn(['text-white', 'bg-black'])).toBe('text-white bg-black');
  });

  it('accepts an object form with boolean flags', () => {
    expect(cn({ 'is-active': true, 'is-hidden': false })).toBe('is-active');
  });
});
