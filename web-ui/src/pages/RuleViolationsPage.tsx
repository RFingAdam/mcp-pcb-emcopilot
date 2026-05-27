import React, { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { rulesApi } from '../api/client';

interface RuleViolation {
  id: string;
  rule_id: string;
  rule_name: string;
  rule_set: string;
  category: string;
  severity: 'critical' | 'error' | 'warning' | 'info';
  message: string;
  location?: {
    x?: number;
    y?: number;
    layer?: string;
    element_id?: string;
    element_type?: string;
  };
  actual_value?: number;
  required_value?: number;
  unit?: string;
  suggestion?: string;
  waived?: boolean;
  waiver_reason?: string;
}

interface RuleResult {
  score: number;
  rules_checked: number;
  rules_passed: number;
  rules_failed: number;
  rules_waived: number;
  critical_count: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  violations: RuleViolation[];
  checked_at: string;
}

const SEVERITY_CONFIG = {
  critical: { color: '#dc2626', bg: '#fef2f2', icon: '🔴', label: 'Critical' },
  error: { color: '#ea580c', bg: '#fff7ed', icon: '🟠', label: 'Error' },
  warning: { color: '#ca8a04', bg: '#fefce8', icon: '🟡', label: 'Warning' },
  info: { color: '#0284c7', bg: '#f0f9ff', icon: '🔵', label: 'Info' },
};

const RULE_SET_LABELS: Record<string, string> = {
  'IPC-2221B': 'IPC-2221B (General Design)',
  'IPC-7351C': 'IPC-7351C (Component Land Patterns)',
  'IPC-2152': 'IPC-2152 (Current Capacity)',
  'Custom': 'Custom Rules',
};

const CATEGORY_ICONS: Record<string, string> = {
  clearance: '📏',
  spacing: '↔️',
  width: '📐',
  annular_ring: '⭕',
  drill: '🔩',
  current: '⚡',
  thermal: '🌡️',
  courtyard: '🏠',
  solder: '🔧',
};

export default function RuleViolationsPage() {
  const { projectId, layoutId } = useParams<{ projectId: string; layoutId: string }>();
  
  const [filters, setFilters] = useState({
    severity: ['critical', 'error', 'warning', 'info'],
    ruleSet: [] as string[],
    category: [] as string[],
    showWaived: false,
    search: '',
  });
  const [groupBy, setGroupBy] = useState<'severity' | 'ruleSet' | 'category' | 'none'>('severity');
  const [selectedViolation, setSelectedViolation] = useState<RuleViolation | null>(null);
  const [showWaiverModal, setShowWaiverModal] = useState(false);

  // Fetch rule check results
  const { data: ruleResult, isLoading, refetch } = useQuery({
    queryKey: ['rule-violations', layoutId],
    queryFn: () => rulesApi.getViolations(Number(layoutId)),
    enabled: !!layoutId,
  });

  // Run new rule check
  const handleRunCheck = async () => {
    await rulesApi.runCheck(Number(layoutId));
    refetch();
  };

  // Export violations
  const handleExport = async (format: 'csv' | 'json' | 'pdf') => {
    const data = await rulesApi.exportViolations(Number(layoutId), format);
    const blob = new Blob([data], { type: format === 'json' ? 'application/json' : 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `violations-${layoutId}.${format}`;
    a.click();
  };

  // Filter violations
  const filteredViolations = useMemo(() => {
    if (!ruleResult?.violations) return [];
    
    return ruleResult.violations.filter((v: RuleViolation) => {
      if (!filters.severity.includes(v.severity)) return false;
      if (filters.ruleSet.length && !filters.ruleSet.includes(v.rule_set)) return false;
      if (filters.category.length && !filters.category.includes(v.category)) return false;
      if (!filters.showWaived && v.waived) return false;
      if (filters.search) {
        const search = filters.search.toLowerCase();
        return (
          v.rule_name.toLowerCase().includes(search) ||
          v.message.toLowerCase().includes(search) ||
          v.location?.element_id?.toLowerCase().includes(search)
        );
      }
      return true;
    });
  }, [ruleResult, filters]);

  // Group violations
  const groupedViolations = useMemo(() => {
    if (groupBy === 'none') return { 'All Violations': filteredViolations };
    
    const groups: Record<string, RuleViolation[]> = {};
    filteredViolations.forEach((v: RuleViolation) => {
      const key = groupBy === 'severity' ? v.severity :
                  groupBy === 'ruleSet' ? v.rule_set :
                  v.category;
      if (!groups[key]) groups[key] = [];
      groups[key].push(v);
    });
    return groups;
  }, [filteredViolations, groupBy]);

  // Get unique values for filters
  const availableRuleSets = useMemo<string[]>(() => {
    if (!ruleResult?.violations) return [];
    return Array.from(new Set(ruleResult.violations.map((v: RuleViolation) => v.rule_set)));
  }, [ruleResult]);

  const availableCategories = useMemo<string[]>(() => {
    if (!ruleResult?.violations) return [];
    return Array.from(new Set(ruleResult.violations.map((v: RuleViolation) => v.category)));
  }, [ruleResult]);

  if (isLoading) {
    return <div className="p-4">Loading rule check results...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <Link to={`/projects/${projectId}`} className="text-blue-600 hover:underline text-sm">
              ← Back to Project
            </Link>
            <h1 className="text-2xl font-bold mt-1">Design Rule Violations</h1>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleRunCheck}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              🔄 Re-run Check
            </button>
            <div className="relative group">
              <button className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200">
                📥 Export
              </button>
              <div className="absolute right-0 mt-1 bg-white border rounded shadow-lg hidden group-hover:block z-10">
                <button onClick={() => handleExport('csv')} className="block px-4 py-2 hover:bg-gray-100 w-full text-left">
                  Export as CSV
                </button>
                <button onClick={() => handleExport('json')} className="block px-4 py-2 hover:bg-gray-100 w-full text-left">
                  Export as JSON
                </button>
                <button onClick={() => handleExport('pdf')} className="block px-4 py-2 hover:bg-gray-100 w-full text-left">
                  Export as PDF
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Score Summary */}
      {ruleResult && (
        <div className="bg-white border-b px-6 py-4">
          <div className="grid grid-cols-6 gap-4">
            <div className="text-center p-4 bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg">
              <div className="text-4xl font-bold text-blue-600">
                {ruleResult.score.toFixed(0)}
              </div>
              <div className="text-sm text-gray-600">Score / 100</div>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl font-bold">{ruleResult.rules_checked}</div>
              <div className="text-sm text-gray-600">Rules Checked</div>
            </div>
            <div className="text-center p-4 bg-red-50 rounded-lg">
              <div className="text-2xl font-bold text-red-600">{ruleResult.critical_count}</div>
              <div className="text-sm text-gray-600">Critical</div>
            </div>
            <div className="text-center p-4 bg-orange-50 rounded-lg">
              <div className="text-2xl font-bold text-orange-600">{ruleResult.error_count}</div>
              <div className="text-sm text-gray-600">Errors</div>
            </div>
            <div className="text-center p-4 bg-yellow-50 rounded-lg">
              <div className="text-2xl font-bold text-yellow-600">{ruleResult.warning_count}</div>
              <div className="text-sm text-gray-600">Warnings</div>
            </div>
            <div className="text-center p-4 bg-green-50 rounded-lg">
              <div className="text-2xl font-bold text-green-600">{ruleResult.rules_passed}</div>
              <div className="text-sm text-gray-600">Passed</div>
            </div>
          </div>
        </div>
      )}

      <div className="flex">
        {/* Filters Sidebar */}
        <div className="w-64 bg-white border-r p-4 min-h-screen">
          <h3 className="font-semibold mb-3">Filters</h3>
          
          {/* Search */}
          <div className="mb-4">
            <input
              type="text"
              placeholder="Search violations..."
              className="w-full px-3 py-2 border rounded"
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            />
          </div>

          {/* Severity Filter */}
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2">Severity</label>
            {Object.entries(SEVERITY_CONFIG).map(([key, config]) => (
              <label key={key} className="flex items-center gap-2 mb-1">
                <input
                  type="checkbox"
                  checked={filters.severity.includes(key)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFilters({ ...filters, severity: [...filters.severity, key] });
                    } else {
                      setFilters({ ...filters, severity: filters.severity.filter(s => s !== key) });
                    }
                  }}
                />
                <span>{config.icon} {config.label}</span>
              </label>
            ))}
          </div>

          {/* Rule Set Filter */}
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2">Rule Set</label>
            {availableRuleSets.map((rs: string) => (
              <label key={rs} className="flex items-center gap-2 mb-1 text-sm">
                <input
                  type="checkbox"
                  checked={filters.ruleSet.includes(rs)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFilters({ ...filters, ruleSet: [...filters.ruleSet, rs] });
                    } else {
                      setFilters({ ...filters, ruleSet: filters.ruleSet.filter(r => r !== rs) });
                    }
                  }}
                />
                <span>{RULE_SET_LABELS[rs] || rs}</span>
              </label>
            ))}
          </div>

          {/* Category Filter */}
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2">Category</label>
            {availableCategories.map((cat: string) => (
              <label key={cat} className="flex items-center gap-2 mb-1 text-sm">
                <input
                  type="checkbox"
                  checked={filters.category.includes(cat)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFilters({ ...filters, category: [...filters.category, cat] });
                    } else {
                      setFilters({ ...filters, category: filters.category.filter(c => c !== cat) });
                    }
                  }}
                />
                <span>{CATEGORY_ICONS[cat] || '📋'} {cat}</span>
              </label>
            ))}
          </div>

          {/* Show Waived */}
          <label className="flex items-center gap-2 mb-4">
            <input
              type="checkbox"
              checked={filters.showWaived}
              onChange={(e) => setFilters({ ...filters, showWaived: e.target.checked })}
            />
            <span>Show waived violations</span>
          </label>

          {/* Group By */}
          <div className="mb-4">
            <label className="block text-sm font-medium mb-2">Group By</label>
            <select
              className="w-full px-3 py-2 border rounded"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as any)}
            >
              <option value="severity">Severity</option>
              <option value="ruleSet">Rule Set</option>
              <option value="category">Category</option>
              <option value="none">No Grouping</option>
            </select>
          </div>
        </div>

        {/* Violations List */}
        <div className="flex-1 p-4">
          <div className="text-sm text-gray-600 mb-3">
            Showing {filteredViolations.length} of {ruleResult?.violations.length || 0} violations
          </div>

          {Object.entries(groupedViolations).map(([group, violations]) => (
            <div key={group} className="mb-6">
              {groupBy !== 'none' && (
                <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                  {groupBy === 'severity' && SEVERITY_CONFIG[group as keyof typeof SEVERITY_CONFIG]?.icon}
                  {groupBy === 'category' && CATEGORY_ICONS[group]}
                  {groupBy === 'ruleSet' ? RULE_SET_LABELS[group] || group : group}
                  <span className="text-sm text-gray-500">({violations.length})</span>
                </h3>
              )}

              <div className="space-y-2">
                {violations.map((violation: RuleViolation) => (
                  <div
                    key={violation.id}
                    className={`bg-white border rounded-lg p-4 cursor-pointer hover:shadow-md transition-shadow ${
                      violation.waived ? 'opacity-60' : ''
                    }`}
                    style={{ borderLeftColor: SEVERITY_CONFIG[violation.severity]?.color, borderLeftWidth: '4px' }}
                    onClick={() => setSelectedViolation(violation)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{violation.rule_name}</span>
                          <span className="text-xs px-2 py-0.5 bg-gray-100 rounded">
                            {violation.rule_set}
                          </span>
                          {violation.waived && (
                            <span className="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded">
                              Waived
                            </span>
                          )}
                        </div>
                        <p className="text-gray-600 text-sm mt-1">{violation.message}</p>
                        {violation.location && (
                          <div className="text-xs text-gray-500 mt-2">
                            📍 {violation.location.element_type}: {violation.location.element_id}
                            {violation.location.layer && ` on ${violation.location.layer}`}
                          </div>
                        )}
                      </div>
                      <div className="text-right">
                        {violation.actual_value !== undefined && violation.required_value !== undefined && (
                          <div className="text-sm">
                            <span className="text-red-600">{violation.actual_value.toFixed(3)}</span>
                            <span className="text-gray-400"> / </span>
                            <span className="text-green-600">{violation.required_value.toFixed(3)}</span>
                            {violation.unit && <span className="text-gray-500 ml-1">{violation.unit}</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {filteredViolations.length === 0 && (
            <div className="text-center text-gray-500 py-12">
              <div className="text-4xl mb-2">✅</div>
              <div>No violations match your filters</div>
            </div>
          )}
        </div>

        {/* Violation Detail Panel */}
        {selectedViolation && (
          <div className="w-96 bg-white border-l p-4 min-h-screen">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold">Violation Details</h3>
              <button
                onClick={() => setSelectedViolation(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-500">Rule</label>
                <div className="font-medium">{selectedViolation.rule_name}</div>
              </div>

              <div>
                <label className="text-xs text-gray-500">Rule Set</label>
                <div>{RULE_SET_LABELS[selectedViolation.rule_set] || selectedViolation.rule_set}</div>
              </div>

              <div>
                <label className="text-xs text-gray-500">Severity</label>
                <div className="flex items-center gap-2">
                  {SEVERITY_CONFIG[selectedViolation.severity]?.icon}
                  {SEVERITY_CONFIG[selectedViolation.severity]?.label}
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500">Message</label>
                <div className="text-sm">{selectedViolation.message}</div>
              </div>

              {selectedViolation.location && (
                <div>
                  <label className="text-xs text-gray-500">Location</label>
                  <div className="text-sm font-mono bg-gray-50 p-2 rounded">
                    {JSON.stringify(selectedViolation.location, null, 2)}
                  </div>
                </div>
              )}

              {selectedViolation.actual_value !== undefined && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-gray-500">Actual Value</label>
                    <div className="text-red-600 font-mono">
                      {selectedViolation.actual_value.toFixed(4)} {selectedViolation.unit}
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500">Required Value</label>
                    <div className="text-green-600 font-mono">
                      {selectedViolation.required_value?.toFixed(4)} {selectedViolation.unit}
                    </div>
                  </div>
                </div>
              )}

              {selectedViolation.suggestion && (
                <div>
                  <label className="text-xs text-gray-500">Suggestion</label>
                  <div className="text-sm bg-blue-50 text-blue-800 p-3 rounded">
                    💡 {selectedViolation.suggestion}
                  </div>
                </div>
              )}

              <div className="border-t pt-4 space-y-2">
                <button
                  onClick={() => setShowWaiverModal(true)}
                  className="w-full px-4 py-2 bg-purple-100 text-purple-700 rounded hover:bg-purple-200"
                >
                  {selectedViolation.waived ? 'Edit Waiver' : 'Request Waiver'}
                </button>
                <button className="w-full px-4 py-2 bg-gray-100 rounded hover:bg-gray-200">
                  🔍 View in Layout
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Waiver Modal */}
      {showWaiverModal && selectedViolation && (
        <WaiverModal
          violation={selectedViolation}
          onClose={() => setShowWaiverModal(false)}
          onSave={async (reason: string) => {
            await rulesApi.addWaiver(Number(layoutId), selectedViolation.rule_id, reason);
            refetch();
            setShowWaiverModal(false);
          }}
        />
      )}
    </div>
  );
}

function WaiverModal({
  violation,
  onClose,
  onSave,
}: {
  violation: RuleViolation;
  onClose: () => void;
  onSave: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState(violation.waiver_reason || '');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(reason);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold mb-4">Request Waiver</h3>
        
        <div className="mb-4">
          <div className="text-sm text-gray-600 mb-2">
            Rule: <span className="font-medium">{violation.rule_name}</span>
          </div>
          <div className="text-sm text-gray-600">
            {violation.message}
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium mb-2">Waiver Reason</label>
          <textarea
            className="w-full px-3 py-2 border rounded"
            rows={4}
            placeholder="Explain why this violation should be waived..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-100 rounded hover:bg-gray-200"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!reason.trim() || saving}
            className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Submit Waiver'}
          </button>
        </div>
      </div>
    </div>
  );
}
