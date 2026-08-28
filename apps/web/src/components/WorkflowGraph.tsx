import { memo, useMemo } from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import type { NodeStatus, WorkflowViewState } from '../types';
import { NODE_LABELS } from '../workflow';

interface StatusNodeData extends Record<string, unknown> {
  label: string;
  status: NodeStatus;
}

const positions: Record<string, { x: number; y: number }> = {
  repository_context: { x: 0, y: 115 },
  task_analysis: { x: 190, y: 115 },
  planning: { x: 380, y: 115 },
  architecture_review: { x: 570, y: 25 },
  repository_analysis: { x: 570, y: 205 },
  approval: { x: 775, y: 115 },
  implementation: { x: 970, y: 115 },
  testing: { x: 1160, y: 115 },
  failure_analysis: { x: 1160, y: 290 },
  repair: { x: 970, y: 290 },
  code_review: { x: 1350, y: 115 },
  final_report: { x: 1540, y: 115 },
};

const edges: Edge[] = [
  ['repository_context', 'task_analysis'],
  ['task_analysis', 'planning'],
  ['planning', 'architecture_review'],
  ['planning', 'repository_analysis'],
  ['architecture_review', 'approval'],
  ['repository_analysis', 'approval'],
  ['approval', 'implementation'],
  ['implementation', 'testing'],
  ['testing', 'code_review'],
  ['testing', 'failure_analysis'],
  ['failure_analysis', 'repair'],
  ['repair', 'testing'],
  ['code_review', 'final_report'],
].map(([source, target], index) => ({
  id: `edge-${index}`,
  source,
  target,
  type: 'smoothstep',
  animated: false,
  markerEnd: { type: MarkerType.ArrowClosed, color: '#48566f' },
  style: { stroke: '#48566f', strokeWidth: 1.4 },
}));

const StatusNode = memo(({ data, selected }: NodeProps<Node<StatusNodeData>>) => (
  <div className={`workflow-node status-${data.status} ${selected ? 'selected' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <span className="node-status-dot" />
    <span>{data.label}</span>
    <small>{data.status}</small>
    <Handle type="source" position={Position.Right} />
  </div>
));

const nodeTypes = { status: StatusNode };

export function WorkflowGraph({
  workflow,
  onSelect,
}: {
  workflow: WorkflowViewState;
  onSelect: (id: string) => void;
}) {
  const nodes = useMemo<Node<StatusNodeData>[]>(
    () =>
      Object.entries(workflow.nodes).map(([id, state]) => ({
        id,
        type: 'status',
        position: positions[id],
        data: { label: NODE_LABELS[id], status: state.status },
        selected: workflow.selectedNode === id,
      })),
    [workflow.nodes, workflow.selectedNode],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.id)}
      fitView
      fitViewOptions={{ padding: 0.16 }}
      minZoom={0.45}
      maxZoom={1.35}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#26334a" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
