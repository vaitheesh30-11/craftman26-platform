'use client';

import { useMemo, useRef, useState } from 'react';
import { useEffect } from 'react';
import { AnimatePresence } from 'framer-motion';
import type { AgentTurnEvent, Coalition, StreamEvent } from '@/types/stream';
import { DebateCard } from './DebateCard';

const coalitions: Coalition[] = ['SUPERVISOR', 'ALPHA_SYNTHESIS', 'BETA_SIMULATION', 'GAMMA_CONTEXT'];
const coalitionLabels: Record<Coalition, string> = { SUPERVISOR: 'Supervisor', ALPHA_SYNTHESIS: 'Alpha', BETA_SIMULATION: 'Beta', GAMMA_CONTEXT: 'Gamma' };

function isAgentTurn(event: StreamEvent): event is AgentTurnEvent {
  return event.event_type === 'AGENT_TURN_EMITTED' && 'coalition' in event && 'agent_id' in event && 'action_taken' in event;
}

export function AgentDebateFeed({ events }: { events: StreamEvent[] }): JSX.Element {
  const [enabledCoalitions, setEnabledCoalitions] = useState<Coalition[]>(coalitions);
  const bottomRef = useRef<HTMLDivElement>(null);
  const turns = useMemo(() => events.filter(isAgentTurn).filter((event) => enabledCoalitions.includes(event.coalition)).slice(-50), [enabledCoalitions, events]);
  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), [turns.length]);
  const toggle = (coalition: Coalition): void => setEnabledCoalitions((current) => current.includes(coalition) ? current.filter((value) => value !== coalition) : [...current, coalition]);
  return <section aria-label="Agent debate feed" className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-4 backdrop-blur-md"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-zinc-100">Agent debate</h2><div className="flex flex-wrap gap-1.5">{coalitions.map((coalition) => { const isEnabled = enabledCoalitions.includes(coalition); return <button key={coalition} aria-pressed={isEnabled} onClick={() => toggle(coalition)} className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all duration-200 ${isEnabled ? 'bg-zinc-700 text-zinc-100 border-zinc-600' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'}`}>{coalitionLabels[coalition]}</button>; })}</div></div><div className="mt-4 max-h-[32rem] space-y-3 overflow-y-auto pr-1">{turns.length === 0 ? <div className="py-12 text-center"><p className="text-sm text-zinc-500">No debate events match the active filters.</p><p className="mt-1 text-xs text-zinc-600">Enable a coalition to see agent turns.</p></div> : <AnimatePresence initial={false}>{turns.map((event) => <DebateCard key={event.event_id} event={event} />)}</AnimatePresence>}<div ref={bottomRef} /></div></section>;
}
