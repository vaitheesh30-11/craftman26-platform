import { useState } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import type { AgentTurnEvent, Coalition } from '@/types/stream';

const coalitionStyles: Record<Coalition, { label: string; accent: string }> = { SUPERVISOR: { label: 'Supervisor', accent: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300' }, ALPHA_SYNTHESIS: { label: 'Alpha · AST', accent: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300' }, BETA_SIMULATION: { label: 'Beta · Proof', accent: 'border-violet-500/50 bg-violet-500/10 text-violet-300' }, GAMMA_CONTEXT: { label: 'Gamma · Context', accent: 'border-amber-500/50 bg-amber-500/10 text-amber-300' } };

export function DebateCard({ event }: { event: AgentTurnEvent }): JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const coalition = coalitionStyles[event.coalition];
  const details = event.tool_parameters ?? (event.formal_feedback ? { formal_feedback: event.formal_feedback } : null);
  return <motion.article layout initial={{ opacity: 0, y: 20, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ type: 'spring', stiffness: 400, damping: 25 }} className={cn('rounded-xl border bg-zinc-900/60 p-4 backdrop-blur-md', coalition.accent)}><div className="flex flex-wrap items-center gap-2"><span className={cn('rounded-full border px-2.5 py-1 text-xs font-semibold', coalition.accent)}>{coalition.label}</span><span className="font-medium text-zinc-100">{event.agent_id}</span><span className="ml-auto text-xs text-zinc-500">{event.execution_duration_ms ?? 0}ms</span></div><p className="mt-3 text-sm leading-6 text-zinc-200">{event.action_taken}</p>{details && <div className="mt-3"><button aria-expanded={isOpen} onClick={() => setIsOpen(!isOpen)} className="text-xs font-medium text-zinc-400 transition hover:text-zinc-100">{isOpen ? 'Hide evidence' : 'View evidence'}</button>{isOpen && <pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-950 p-3 text-xs leading-5 text-zinc-300">{JSON.stringify(details, null, 2)}</pre>}</div>}</motion.article>;
}
