import { useCallback, useEffect, useReducer, useState } from 'react';
import { createRun, decideRun, getRun, streamEvents, type CreateRunInput } from '../api';
import type { RunEvent, RunRecord } from '../types';
import { initialWorkflowState, reduceWorkflowEvent } from '../workflow';

export function useRun() {
  const [run, setRun] = useState<RunRecord>();
  const [workflow, dispatch] = useReducer(reduceWorkflowEvent, undefined, initialWorkflowState);
  const [error, setError] = useState<string>();
  const [starting, setStarting] = useState(false);

  const refresh = useCallback(async (runId: string) => {
    setRun(await getRun(runId));
  }, []);

  useEffect(() => {
    if (!run?.run_id) return;
    const source = new AbortController();
    let sequence = 0;
    const receive = (event: RunEvent) => {
      sequence = Math.max(sequence, event.sequence);
      dispatch(event);
      if (
        ['approval.required', 'run.completed', 'run.stopped', 'run.failed'].includes(
          event.event_type,
        )
      ) {
        void refresh(run.run_id).catch((cause: unknown) => setError(String(cause)));
      }
      if (['run.completed', 'run.stopped', 'run.failed'].includes(event.event_type)) {
        source.abort();
      }
    };
    const connect = async () => {
      while (!source.signal.aborted) {
        try {
          await streamEvents(run.run_id, receive, source.signal, sequence);
        } catch (cause) {
          if (!source.signal.aborted) {
            setError(`Live event connection interrupted; retrying: ${String(cause)}`);
          }
        }
        if (!source.signal.aborted) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
      }
    };
    void connect();
    return () => source.abort();
  }, [refresh, run?.run_id]);

  const start = useCallback(async (input: CreateRunInput) => {
    setStarting(true);
    setError(undefined);
    try {
      setRun(await createRun(input));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStarting(false);
    }
  }, []);

  const decide = useCallback(
    async (action: 'approve' | 'reject', reason?: string) => {
      if (!run) return;
      setError(undefined);
      try {
        setRun(await decideRun(run.run_id, action, 'web-user', reason));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [run],
  );

  return { run, workflow, dispatch, start, decide, starting, error };
}
