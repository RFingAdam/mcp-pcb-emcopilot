import React, { useState, useMemo } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { rulesApi } from '../api/client';

interface CustomRule {
  id: string;
  name: string;
  description: string;
  category: string;
  severity: 'critical' | 'error' | 'warning' | 'info';
  enabled: boolean;
  conditions: RuleCondition[];
  message_template: string;
  suggestion_template?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

interface RuleCondition {
  id: string;
  field: string;
  operator: string;
  value: string | number;
  unit?: string;
  context_dependent?: boolean;
  context_field?: string;
}

interface RuleWaiver {
  id: string;
  layout_id: number;
  rule_id: string;
  rule_name: string;
  reason: string;
  requested_by: string;
  requested_at: string;
  approved_by?: string;
  approved_at?: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  expires_at?: string;
  affected_violations: number;
}

const CATEGORIES = [
  { id: 'clearance', label: 'Clearance', icon: '📏' },
  { id: 'spacing', label: 'Spacing', icon: '↔️' },
  { id: 'width', label: 'Trace Width', icon: '📐' },
  { id: 'annular_ring', label: 'Annular Ring', icon: '⭕' },
  { id: 'drill', label: 'Drill/Via', icon: '🔩' },
  { id: 'current', label: 'Current Capacity', icon: '⚡' },
  { id: 'thermal', label: 'Thermal', icon: '🌡️' },
  { id: 'impedance', label: 'Impedance', icon: '〰️' },
  { id: 'signal_integrity', label: 'Signal Integrity', icon: '📶' },
  { id: 'emc', label: 'EMC', icon: '📡' },
  { id: 'dfm', label: 'DFM', icon: '🏭' },
  { id: 'custom', label: 'Custom', icon: '⚙️' },
];

const OPERATORS = [
  { id: 'gte', label: '≥ (Greater than or equal)' },
  { id: 'gt', label: '> (Greater than)' },
  { id: 'lte', label: '≤ (Less than or equal)' },
  { id: 'lt', label: '< (Less than)' },
  { id: 'eq', label: '= (Equal to)' },
  { id: 'neq', label: '≠ (Not equal to)' },
  { id: 'between', label: 'Between' },
  { id: 'contains', label: 'Contains' },
  { id: 'matches', label: 'Matches (regex)' },
];

const FIELDS = [
  { id: 'trace.width_mm', label: 'Trace Width (mm)', category: 'width' },
  { id: 'trace.clearance_mm', label: 'Trace Clearance (mm)', category: 'clearance' },
  { id: 'trace.length_mm', label: 'Trace Length (mm)', category: 'signal_integrity' },
  { id: 'trace.impedance_ohm', label: 'Trace Impedance (Ω)', category: 'impedance' },
  { id: 'via.drill_mm', label: 'Via Drill (mm)', category: 'drill' },
  { id: 'via.pad_mm', label: 'Via Pad (mm)', category: 'drill' },
  { id: 'via.annular_ring_mm', label: 'Via Annular Ring (mm)', category: 'annular_ring' },
  { id: 'via.aspect_ratio', label: 'Via Aspect Ratio', category: 'drill' },
  { id: 'component.spacing_mm', label: 'Component Spacing (mm)', category: 'spacing' },
  { id: 'component.courtyard_mm', label: 'Component Courtyard (mm)', category: 'spacing' },
  { id: 'plane.clearance_mm', label: 'Plane Clearance (mm)', category: 'clearance' },
  { id: 'plane.slot_width_mm', label: 'Plane Slot Width (mm)', category: 'emc' },
  { id: 'copper.edge_clearance_mm', label: 'Copper to Edge (mm)', category: 'clearance' },
  { id: 'solder_mask.expansion_mm', label: 'Solder Mask Expansion (mm)', category: 'dfm' },
];

const SEVERITIES = [
  { id: 'critical', label: 'Critical', color: 'bg-red-100 text-red-700', icon: '🔴' },
  { id: 'error', label: 'Error', color: 'bg-orange-100 text-orange-700', icon: '🟠' },
  { id: 'warning', label: 'Warning', color: 'bg-yellow-100 text-yellow-700', icon: '🟡' },
  { id: 'info', label: 'Info', color: 'bg-blue-100 text-blue-700', icon: '🔵' },
];

export default function RuleEditorPage() {
  const { projectId, ruleId } = useParams<{ projectId: string; ruleId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  
  const [activeTab, setActiveTab] = useState<'rules' | 'waivers'>('rules');
  const [editingRule, setEditingRule] = useState<CustomRule | null>(null);
  const [showEditor, setShowEditor] = useState(false);

  // Fetch custom rules
  const { data: customRules = [], isLoading: rulesLoading } = useQuery({
    queryKey: ['custom-rules', projectId],
    queryFn: () => rulesApi.getCustomRules(Number(projectId)),
  });

  // Fetch waivers
  const { data: waivers = [], isLoading: waiversLoading } = useQuery({
    queryKey: ['waivers', projectId],
    queryFn: () => rulesApi.getWaivers(Number(projectId)),
  });

  // Mutations
  const createRuleMutation = useMutation({
    mutationFn: (rule: Partial<CustomRule>) => rulesApi.createCustomRule(Number(projectId), rule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-rules', projectId] });
      setShowEditor(false);
      setEditingRule(null);
    },
  });

  const updateRuleMutation = useMutation({
    mutationFn: ({ ruleId, rule }: { ruleId: string; rule: Partial<CustomRule> }) =>
      rulesApi.updateCustomRule(Number(projectId), ruleId, rule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-rules', projectId] });
      setShowEditor(false);
      setEditingRule(null);
    },
  });

  const deleteRuleMutation = useMutation({
    mutationFn: (ruleId: string) => rulesApi.deleteCustomRule(Number(projectId), ruleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-rules', projectId] });
    },
  });

  const updateWaiverMutation = useMutation({
    mutationFn: ({ waiverId, status }: { waiverId: string; status: string }) =>
      rulesApi.updateWaiver(Number(projectId), waiverId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['waivers', projectId] });
    },
  });

  const handleNewRule = () => {
    setEditingRule({
      id: '',
      name: '',
      description: '',
      category: 'custom',
      severity: 'warning',
      enabled: true,
      conditions: [],
      message_template: '',
      suggestion_template: '',
      created_by: 'current_user',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    setShowEditor(true);
  };

  const handleEditRule = (rule: CustomRule) => {
    setEditingRule({ ...rule });
    setShowEditor(true);
  };

  const handleSaveRule = (rule: CustomRule) => {
    if (rule.id) {
      updateRuleMutation.mutate({ ruleId: rule.id, rule });
    } else {
      createRuleMutation.mutate(rule);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <Link to={`/projects/${projectId}`} className="text-blue-600 hover:underline text-sm">
              ← Back to Project
            </Link>
            <h1 className="text-2xl font-bold mt-1">Design Rule Management</h1>
          </div>
          <button
            onClick={handleNewRule}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            + Create Custom Rule
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border-b px-6">
        <div className="flex gap-4">
          <button
            onClick={() => setActiveTab('rules')}
            className={`py-3 px-4 border-b-2 font-medium ${
              activeTab === 'rules'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            📋 Custom Rules ({customRules.length})
          </button>
          <button
            onClick={() => setActiveTab('waivers')}
            className={`py-3 px-4 border-b-2 font-medium ${
              activeTab === 'waivers'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            ✋ Waivers ({waivers.filter((w: RuleWaiver) => w.status === 'pending').length} pending)
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-6">
        {activeTab === 'rules' && (
          <CustomRulesList
            rules={customRules}
            loading={rulesLoading}
            onEdit={handleEditRule}
            onDelete={(id: string) => deleteRuleMutation.mutate(id)}
            onToggle={(id: string, enabled: boolean) =>
              updateRuleMutation.mutate({ ruleId: id, rule: { enabled } })
            }
          />
        )}

        {activeTab === 'waivers' && (
          <WaiversList
            waivers={waivers}
            loading={waiversLoading}
            onApprove={(id: string) => updateWaiverMutation.mutate({ waiverId: id, status: 'approved' })}
            onReject={(id: string) => updateWaiverMutation.mutate({ waiverId: id, status: 'rejected' })}
          />
        )}
      </div>

      {/* Rule Editor Modal */}
      {showEditor && editingRule && (
        <RuleEditorModal
          rule={editingRule}
          onSave={handleSaveRule}
          onClose={() => {
            setShowEditor(false);
            setEditingRule(null);
          }}
        />
      )}
    </div>
  );
}

function CustomRulesList({
  rules,
  loading,
  onEdit,
  onDelete,
  onToggle,
}: {
  rules: CustomRule[];
  loading: boolean;
  onEdit: (rule: CustomRule) => void;
  onDelete: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
}) {
  const [filter, setFilter] = useState({ category: '', search: '' });

  const filteredRules = useMemo(() => {
    return rules.filter((rule: CustomRule) => {
      if (filter.category && rule.category !== filter.category) return false;
      if (filter.search) {
        const search = filter.search.toLowerCase();
        return (
          rule.name.toLowerCase().includes(search) ||
          rule.description.toLowerCase().includes(search)
        );
      }
      return true;
    });
  }, [rules, filter]);

  if (loading) {
    return <div>Loading custom rules...</div>;
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <input
          type="text"
          placeholder="Search rules..."
          className="px-3 py-2 border rounded flex-1 max-w-md"
          value={filter.search}
          onChange={(e) => setFilter({ ...filter, search: e.target.value })}
        />
        <select
          className="px-3 py-2 border rounded"
          value={filter.category}
          onChange={(e) => setFilter({ ...filter, category: e.target.value })}
        >
          <option value="">All Categories</option>
          {CATEGORIES.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.icon} {cat.label}
            </option>
          ))}
        </select>
      </div>

      {/* Rules List */}
      {filteredRules.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <div className="text-4xl mb-2">📋</div>
          <div>No custom rules yet. Create one to get started!</div>
        </div>
      ) : (
        <div className="bg-white rounded-lg border divide-y">
          {filteredRules.map((rule: CustomRule) => (
            <div key={rule.id} className="p-4 flex items-center justify-between hover:bg-gray-50">
              <div className="flex items-center gap-4">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    onChange={(e) => onToggle(rule.id, e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
                <div className={rule.enabled ? '' : 'opacity-50'}>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{rule.name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      SEVERITIES.find(s => s.id === rule.severity)?.color
                    }`}>
                      {SEVERITIES.find(s => s.id === rule.severity)?.icon} {rule.severity}
                    </span>
                    <span className="text-xs px-2 py-0.5 bg-gray-100 rounded">
                      {CATEGORIES.find(c => c.id === rule.category)?.icon} {rule.category}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mt-1">{rule.description}</p>
                  <div className="text-xs text-gray-400 mt-1">
                    {rule.conditions.length} condition{rule.conditions.length !== 1 ? 's' : ''}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onEdit(rule)}
                  className="px-3 py-1 text-sm bg-gray-100 rounded hover:bg-gray-200"
                >
                  Edit
                </button>
                <button
                  onClick={() => {
                    if (confirm('Delete this rule?')) onDelete(rule.id);
                  }}
                  className="px-3 py-1 text-sm text-red-600 hover:bg-red-50 rounded"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WaiversList({
  waivers,
  loading,
  onApprove,
  onReject,
}: {
  waivers: RuleWaiver[];
  loading: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>('pending');

  const filteredWaivers = useMemo(() => {
    if (!statusFilter) return waivers;
    return waivers.filter((w: RuleWaiver) => w.status === statusFilter);
  }, [waivers, statusFilter]);

  if (loading) {
    return <div>Loading waivers...</div>;
  }

  return (
    <div>
      {/* Status Filter */}
      <div className="flex gap-2 mb-4">
        {['pending', 'approved', 'rejected', 'expired', ''].map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`px-3 py-1 rounded ${
              statusFilter === status
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            {status || 'All'}
          </button>
        ))}
      </div>

      {/* Waivers List */}
      {filteredWaivers.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <div className="text-4xl mb-2">✅</div>
          <div>No waivers to show</div>
        </div>
      ) : (
        <div className="bg-white rounded-lg border divide-y">
          {filteredWaivers.map((waiver: RuleWaiver) => (
            <div key={waiver.id} className="p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{waiver.rule_name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      waiver.status === 'pending' ? 'bg-yellow-100 text-yellow-700' :
                      waiver.status === 'approved' ? 'bg-green-100 text-green-700' :
                      waiver.status === 'rejected' ? 'bg-red-100 text-red-700' :
                      'bg-gray-100 text-gray-700'
                    }`}>
                      {waiver.status}
                    </span>
                    <span className="text-xs text-gray-500">
                      {waiver.affected_violations} violation{waiver.affected_violations !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mt-1">
                    <strong>Reason:</strong> {waiver.reason}
                  </p>
                  <div className="text-xs text-gray-400 mt-2">
                    Requested by {waiver.requested_by} on {new Date(waiver.requested_at).toLocaleDateString()}
                    {waiver.expires_at && (
                      <span> • Expires {new Date(waiver.expires_at).toLocaleDateString()}</span>
                    )}
                  </div>
                  {waiver.approved_by && (
                    <div className="text-xs text-gray-400">
                      {waiver.status === 'approved' ? 'Approved' : 'Rejected'} by {waiver.approved_by} on{' '}
                      {new Date(waiver.approved_at!).toLocaleDateString()}
                    </div>
                  )}
                </div>
                {waiver.status === 'pending' && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => onApprove(waiver.id)}
                      className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700"
                    >
                      ✓ Approve
                    </button>
                    <button
                      onClick={() => onReject(waiver.id)}
                      className="px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
                    >
                      ✕ Reject
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RuleEditorModal({
  rule,
  onSave,
  onClose,
}: {
  rule: CustomRule;
  onSave: (rule: CustomRule) => void;
  onClose: () => void;
}) {
  const [formData, setFormData] = useState<CustomRule>(rule);
  const [activeSection, setActiveSection] = useState<'basic' | 'conditions' | 'message'>('basic');

  const addCondition = () => {
    setFormData({
      ...formData,
      conditions: [
        ...formData.conditions,
        {
          id: `cond_${Date.now()}`,
          field: 'trace.width_mm',
          operator: 'gte',
          value: 0,
        },
      ],
    });
  };

  const updateCondition = (index: number, updates: Partial<RuleCondition>) => {
    const newConditions = [...formData.conditions];
    newConditions[index] = { ...newConditions[index], ...updates };
    setFormData({ ...formData, conditions: newConditions });
  };

  const removeCondition = (index: number) => {
    setFormData({
      ...formData,
      conditions: formData.conditions.filter((_, i) => i !== index),
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(formData);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-hidden">
        <div className="border-b px-6 py-4 flex justify-between items-center">
          <h3 className="text-lg font-semibold">
            {rule.id ? 'Edit Rule' : 'Create Custom Rule'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>

        {/* Section Tabs */}
        <div className="border-b px-6 flex gap-4">
          {[
            { id: 'basic', label: '1. Basic Info' },
            { id: 'conditions', label: '2. Conditions' },
            { id: 'message', label: '3. Messages' },
          ].map((section) => (
            <button
              key={section.id}
              onClick={() => setActiveSection(section.id as any)}
              className={`py-3 border-b-2 font-medium ${
                activeSection === section.id
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500'
              }`}
            >
              {section.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div className="p-6 overflow-y-auto max-h-[60vh]">
            {/* Basic Info Section */}
            {activeSection === 'basic' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Rule Name</label>
                  <input
                    type="text"
                    className="w-full px-3 py-2 border rounded"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="e.g., Minimum high-speed trace width"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Description</label>
                  <textarea
                    className="w-full px-3 py-2 border rounded"
                    rows={3}
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Describe what this rule checks and why it's important"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Category</label>
                    <select
                      className="w-full px-3 py-2 border rounded"
                      value={formData.category}
                      onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    >
                      {CATEGORIES.map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.icon} {cat.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-1">Severity</label>
                    <select
                      className="w-full px-3 py-2 border rounded"
                      value={formData.severity}
                      onChange={(e) => setFormData({ ...formData, severity: e.target.value as any })}
                    >
                      {SEVERITIES.map((sev) => (
                        <option key={sev.id} value={sev.id}>
                          {sev.icon} {sev.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            )}

            {/* Conditions Section */}
            {activeSection === 'conditions' && (
              <div className="space-y-4">
                <p className="text-sm text-gray-600 mb-4">
                  Define conditions that must be met for a violation. All conditions must be satisfied (AND logic).
                </p>

                {formData.conditions.length === 0 ? (
                  <div className="text-center py-8 bg-gray-50 rounded border-2 border-dashed">
                    <div className="text-gray-400 mb-2">No conditions yet</div>
                    <button
                      type="button"
                      onClick={addCondition}
                      className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                      + Add Condition
                    </button>
                  </div>
                ) : (
                  <>
                    {formData.conditions.map((condition, index) => (
                      <div key={condition.id} className="p-4 bg-gray-50 rounded border">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium">Condition {index + 1}</span>
                          <button
                            type="button"
                            onClick={() => removeCondition(index)}
                            className="text-red-500 hover:text-red-700 text-sm"
                          >
                            Remove
                          </button>
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                          <select
                            className="px-3 py-2 border rounded"
                            value={condition.field}
                            onChange={(e) => updateCondition(index, { field: e.target.value })}
                          >
                            {FIELDS.map((field) => (
                              <option key={field.id} value={field.id}>
                                {field.label}
                              </option>
                            ))}
                          </select>
                          <select
                            className="px-3 py-2 border rounded"
                            value={condition.operator}
                            onChange={(e) => updateCondition(index, { operator: e.target.value })}
                          >
                            {OPERATORS.map((op) => (
                              <option key={op.id} value={op.id}>
                                {op.label}
                              </option>
                            ))}
                          </select>
                          <input
                            type="text"
                            className="px-3 py-2 border rounded"
                            value={condition.value}
                            onChange={(e) => updateCondition(index, { 
                              value: isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)
                            })}
                            placeholder="Value"
                          />
                        </div>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={addCondition}
                      className="w-full py-2 border-2 border-dashed rounded text-gray-500 hover:text-gray-700 hover:border-gray-400"
                    >
                      + Add Another Condition
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Messages Section */}
            {activeSection === 'message' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Violation Message</label>
                  <textarea
                    className="w-full px-3 py-2 border rounded font-mono text-sm"
                    rows={3}
                    value={formData.message_template}
                    onChange={(e) => setFormData({ ...formData, message_template: e.target.value })}
                    placeholder="{element_type} '{element_id}' has {field} of {actual_value}{unit}, minimum is {required_value}{unit}"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Available variables: {'{element_type}'}, {'{element_id}'}, {'{field}'}, {'{actual_value}'}, {'{required_value}'}, {'{unit}'}
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Suggestion (Optional)</label>
                  <textarea
                    className="w-full px-3 py-2 border rounded font-mono text-sm"
                    rows={2}
                    value={formData.suggestion_template}
                    onChange={(e) => setFormData({ ...formData, suggestion_template: e.target.value })}
                    placeholder="Increase {field} to at least {required_value}{unit}"
                  />
                </div>

                {/* Preview */}
                <div className="p-4 bg-gray-50 rounded border">
                  <div className="text-sm font-medium mb-2">Preview</div>
                  <div className="text-sm">
                    {formData.message_template
                      .replace('{element_type}', 'Trace')
                      .replace('{element_id}', 'T123')
                      .replace('{field}', 'width')
                      .replace('{actual_value}', '0.10')
                      .replace('{required_value}', '0.15')
                      .replace(/{unit}/g, 'mm') || 'Enter a message template above'}
                  </div>
                  {formData.suggestion_template && (
                    <div className="text-sm text-blue-600 mt-2">
                      💡 {formData.suggestion_template
                        .replace('{field}', 'width')
                        .replace('{required_value}', '0.15')
                        .replace(/{unit}/g, 'mm')}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="border-t px-6 py-4 flex justify-between bg-gray-50">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200"
            >
              Cancel
            </button>
            <div className="flex gap-2">
              {activeSection !== 'basic' && (
                <button
                  type="button"
                  onClick={() => setActiveSection(
                    activeSection === 'message' ? 'conditions' : 'basic'
                  )}
                  className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200"
                >
                  ← Back
                </button>
              )}
              {activeSection !== 'message' ? (
                <button
                  type="button"
                  onClick={() => setActiveSection(
                    activeSection === 'basic' ? 'conditions' : 'message'
                  )}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Next →
                </button>
              ) : (
                <button
                  type="submit"
                  className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                  disabled={!formData.name || formData.conditions.length === 0}
                >
                  {rule.id ? 'Save Changes' : 'Create Rule'}
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
