'use client';

import { DiffEditor, type DiffOnMount } from '@monaco-editor/react';
import { useEffect, useMemo, useState } from 'react';
import { ByteQuotaGauge } from './ByteQuotaGauge';

interface ASTDiffEditorProps { baselinePolicyJson: string; workingPolicyJson: string; onTargetPolicyChange: (value: string, isValid: boolean) => void; }

function formatJson(value: string): string { try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; } }

const awsPolicySchema = {
  type: 'object', required: ['Version', 'Statement'], additionalProperties: false,
  properties: {
    Version: { type: 'string', enum: ['2012-10-17', '2008-10-17'] },
    Id: { type: 'string' },
    Statement: { type: 'array', minItems: 1, items: { type: 'object', required: ['Effect'], allOf: [{ anyOf: [{ required: ['Action'] }, { required: ['NotAction'] }] }, { anyOf: [{ required: ['Resource'] }, { required: ['NotResource'] }] }], additionalProperties: true, properties: { Sid: { type: 'string' }, Effect: { type: 'string', enum: ['Allow', 'Deny'] }, Action: { oneOf: [{ type: 'string' }, { type: 'array', minItems: 1, items: { type: 'string' } }] }, NotAction: { oneOf: [{ type: 'string' }, { type: 'array', minItems: 1, items: { type: 'string' } }] }, Resource: { oneOf: [{ type: 'string' }, { type: 'array', minItems: 1, items: { type: 'string' } }] }, NotResource: { oneOf: [{ type: 'string' }, { type: 'array', minItems: 1, items: { type: 'string' } }] }, Principal: {} } } }
  }
};

export function ASTDiffEditor({ baselinePolicyJson, workingPolicyJson, onTargetPolicyChange }: ASTDiffEditorProps): JSX.Element {
  const [isManualOverride, setIsManualOverride] = useState(false);
  const [target, setTarget] = useState(workingPolicyJson);
  const [isValid, setIsValid] = useState(true);
  useEffect(() => { setTarget(workingPolicyJson); setIsValid(true); onTargetPolicyChange(workingPolicyJson, true); }, [onTargetPolicyChange, workingPolicyJson]);
  const options = useMemo(() => ({ renderSideBySide: true, readOnly: !isManualOverride, minimap: { enabled: false }, automaticLayout: true, fontSize: 13, lineHeight: 21, scrollBeyondLastLine: false, wordWrap: 'on' as const, originalEditable: false }), [isManualOverride]);
  const handleChange = (value: string | undefined): void => { const next = value ?? ''; let valid = true; try { JSON.parse(next); } catch { valid = false; } setTarget(next); setIsValid(valid); onTargetPolicyChange(next, valid); };
  const handleMount: DiffOnMount = (editor, monaco) => {
    monaco.languages.json.jsonDefaults.setDiagnosticsOptions({ validate: true, allowComments: false, schemas: [{ uri: 'https://sentinel-iq.local/schemas/aws-policy.json', fileMatch: ['*'], schema: awsPolicySchema }] });
    const modifiedEditor = editor.getModifiedEditor();
    modifiedEditor.onDidChangeModelContent(() => handleChange(modifiedEditor.getValue()));
  };
  return <section className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/60 shadow-2xl shadow-black/20"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3"><div><h2 className="font-semibold text-zinc-100">Policy AST review</h2><p className="mt-0.5 text-xs text-zinc-500">Original policy is immutable. Manual changes require a fresh proof.</p></div><button type="button" aria-pressed={isManualOverride} onClick={() => setIsManualOverride((current) => !current)} className={`rounded-lg border px-3 py-2 text-xs font-semibold transition ${isManualOverride ? 'border-violet-400/60 bg-violet-500/15 text-violet-200' : 'border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-500'}`}>{isManualOverride ? 'Manual override enabled' : 'Enable manual override'}</button></div><div className="h-[28rem] min-h-[22rem]"><DiffEditor theme="vs-dark" language="json" original={formatJson(baselinePolicyJson)} modified={target} onMount={handleMount} options={options} loading={<div className="grid h-full place-items-center text-sm text-zinc-500">Loading policy editor…</div>} /></div>{!isValid && <p role="alert" className="border-x border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">Invalid JSON detected. Fix syntax before continuing.</p>}<ByteQuotaGauge value={target} /></section>;
}
