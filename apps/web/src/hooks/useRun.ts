import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { createRun, decideRun, eventsUrl, getRun, type CreateRunInput } from '../api';
import type { RunEvent, RunRecord } from '../types';
import { initialWorkflowState, reduceWorkflowEvent } from '../workflow';

const EVENT_TYPES = [
  'run.created',
  'run.started',
  'run.resumed',
  'node.started',
  'node.completed',
  'node.failed',
  'approval.required',
  'approval.decided',
  'run.completed',
  'run.stopped',
  'run.failed',
];

export function useRun() {
  const [run, setRun] = useState<RunRecord>();
  const [workflow, dispatch] = useReducer(reduceWorkflowEvent, undefined, initialWorkflowState);
  const [error, setError] = useState<string>();
  const [starting, setStarting] = useState(false);
  const sourceRef = useRef<EventSource | undefined>(undefined);

  const refresh = useCallback(async (runId: string) => {
    setRun(await getRun(runId));
  }, []);

  useEffect(() => {
    if (!run?.run_id) return;
    const source = new EventSource(eventsUrl(run.run_id));
    sourceRef.current = source;
    const receive = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent;
      dispatch(event);
      if (
        ['approval.required', 'run.completed', 'run.stopped', 'run.failed'].includes(
          event.event_type,
        )
      ) {
        void refresh(run.run_id).catch((cause: unknown) => setError(String(cause)));
      }
      if (['run.completed', 'run.stopped', 'run.failed'].includes(event.event_type)) {
        source.onerror = null;
        source.close();
      }
    };
    EVENT_TYPES.forEach((eventType) => source.addEventListener(eventType, receive));
    source.onerror = () =>
      setError('Live event connection interrupted; the browser will retry automatically.');
    return () => source.close();
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
