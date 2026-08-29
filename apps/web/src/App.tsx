import { useMemo } from 'react';
import { ApprovalPanel } from './components/ApprovalPanel';
import { NodeInspector } from './components/NodeInspector';
import { RunForm } from './components/RunForm';
import { WorkflowGraph } from './components/WorkflowGraph';
import { useRun } from './hooks/useRun';
import { modelUsage } from './workflow';

function elapsed(start?: string, end?: string): string {
  if (!start) return '—';
  const milliseconds = new Date(end ?? Date.now()).getTime() - new Date(start).getTime();
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
}

export function App() {
  const { run, workflow, dispatch, start, decide, starting, error } = useRun();
  const usage = useMemo(() => modelUsage(workflow.events), [workflow.events]);
  const selected = workflow.nodes[workflow.selectedNode];
  const terminal = ['completed', 'failed', 'rejected'].includes(run?.status ?? '');

  return (
    <main>
      <header className="topbar">
        <div className="brand-mark">TP</div>
        <div>
          <strong>TaskPilot AI</strong>
          <span>Engineering orchestration control plane</span>
        </div>
        <div className="environment">
          <i /> Local environment
        </div>
      </header>

      {!run ? (
        <section className="launch-layout">
          <div className="launch-copy">
            <span className="kicker">Controlled delivery, visible decisions</span>
            <h2>Engineering work should be observable before it is autonomous.</h2>
            <p>
              Plan, approve, implement, validate, repair, and review through one durable graph.
              Every transition remains inspectable.
            </p>
          </div>
          <RunForm onSubmit={(value) => void start(value)} disabled={starting} />
        </section>
      ) : (
        <>
          <section className="run-summary">
            <div>
              <div className="eyebrow">Active run · {run.run_id.slice(0, 8)}</div>
              <h1>{run.task}</h1>
              <p>{run.repository}</p>
            </div>
            <div className="summary-metrics">
              <div>
                <span>Status</span>
                <strong className={`run-status ${run.status}`}>
                  {run.status.replaceAll('_', ' ')}
                </strong>
              </div>
              <div>
                <span>Duration</span>
                <strong>{elapsed(run.created_at, terminal ? run.updated_at : undefined)}</strong>
              </div>
              <div>
                <span>Model calls</span>
                <strong>{usage.calls}</strong>
              </div>
              <div>
                <span>Tokens</span>
                <strong>{usage.input + usage.output || '—'}</strong>
              </div>
            </div>
          </section>

          {workflow.approvalPayload && (
            <ApprovalPanel
              payload={workflow.approvalPayload}
              onDecision={(action, reason) => void decide(action, reason)}
            />
          )}

          <section className="workspace-grid">
            <div className="graph-panel panel">
              <div className="panel-title">
                <div>
                  <div className="eyebrow">Execution graph</div>
                  <h2>Delivery workflow</h2>
                </div>
                <div className="legend">
                  <span className="complete" /> Complete <span className="active" /> Active{' '}
                  <span className="wait" /> Waiting <span className="failed" /> Failed
                </div>
              </div>
              <WorkflowGraph
                workflow={workflow}
                onSelect={(selectedNode) =>
                  dispatch({
                    run_id: run.run_id,
                    sequence: workflow.events.length + 1,
                    event_type: 'ui.selection',
                    node: selectedNode,
                    data: {},
                    created_at: new Date().toISOString(),
                  })
                }
              />
            </div>
            <NodeInspector
              nodeId={workflow.selectedNode}
              state={selected}
              events={workflow.events}
            />
          </section>

          {run.final_report && (
            <section className="report panel">
              <div className="eyebrow">Final engineering report</div>
              <h2>{run.final_report.summary}</h2>
              {run.final_report.stop_reason && (
                <p className="error-text">{run.final_report.stop_reason}</p>
              )}
              <div className="report-grid">
                <div>
                  <span>Changed files</span>
                  <strong>{run.final_report.changed_files.length}</strong>
                </div>
                <div>
                  <span>Validation</span>
                  <p>{run.final_report.validation_summary ?? '—'}</p>
                </div>
                <div>
                  <span>Review</span>
                  <p>{run.final_report.review_summary ?? '—'}</p>
                </div>
              </div>
            </section>
          )}
        </>
      )}
      {error && (
        <div className="toast" role="alert">
          {error}
        </div>
      )}
    </main>
  );
}
