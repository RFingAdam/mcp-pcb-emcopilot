import React, { useState, useMemo, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { analysisApi, layoutsApi } from '../api/client';
import { PCBViewer } from '../components/PCBViewer';

interface Violation {
  id: number;
  category: 'rf_si' | 'emc' | 'dfm' | 'drc';
  severity: 'error' | 'warning' | 'info';
  rule_name: string;
  message: string;
  location?: {
    x?: number;
    y?: number;
    layer?: string;
    net?: string;
    component?: string;
  };
  details?: Record<string, any>;
}

interface FilterState {
  severity: string[];
  category: string[];
  search: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  error: '#dc3545',
  warning: '#ffc107',
  info: '#17a2b8',
};

const CATEGORY_LABELS: Record<string, string> = {
  rf_si: 'RF/SI',
  emc: 'EMC',
  dfm: 'DFM',
  drc: 'DRC',
};

export default function ViolationsPanel() {
  const { projectId, layoutId } = useParams<{ projectId: string; layoutId: string }>();
  const [filters, setFilters] = useState<FilterState>({
    severity: ['error', 'warning', 'info'],
    category: ['rf_si', 'emc', 'dfm', 'drc'],
    search: '',
  });
  const [selectedViolation, setSelectedViolation] = useState<Violation | null>(null);
  const [sortBy, setSortBy] = useState<'severity' | 'category' | 'rule_name'>('severity');
  const [showViewer, setShowViewer] = useState(true);

  // Fetch violations from API
  const { data: violations = [], isLoading, error } = useQuery({
    queryKey: ['violations', layoutId],
    queryFn: () => analysisApi.getViolations(Number(layoutId)),
    enabled: !!layoutId,
  });

  // Fetch PCB data for viewer
  const { data: pcbData } = useQuery({
    queryKey: ['pcb-data', layoutId],
    queryFn: () => layoutsApi.getPCBData(Number(layoutId)),
    enabled: !!layoutId,
  });

  // Hover state for net highlighting
  const [hoveredViolation, setHoveredViolation] = useState<Violation | null>(null);

  // Convert violations to PCBViewer format
  const viewerViolations = useMemo(() => {
    return violations.map((v: Violation) => ({
      id: String(v.id),
      type: v.rule_name,
      severity: v.severity,
      message: v.message,
      location: {
        x: v.location?.x ?? 0,
        y: v.location?.y ?? 0,
      },
      affected_features: [],
      net_name: v.location?.net,  // Include net for highlighting
    }));
  }, [violations]);

  // Get the currently highlighted net (from hover or selection)
  const highlightedNet = useMemo(() => {
    const activeViolation = hoveredViolation || selectedViolation;
    return activeViolation?.location?.net || null;
  }, [hoveredViolation, selectedViolation]);

  // Filter and sort violations
  const filteredViolations = useMemo(() => {
    let result = violations.filter((v: Violation) => {
      // Severity filter
      if (!filters.severity.includes(v.severity)) return false;
      // Category filter
      if (!filters.category.includes(v.category)) return false;
      // Search filter
      if (filters.search) {
        const searchLower = filters.search.toLowerCase();
        return (
          v.rule_name.toLowerCase().includes(searchLower) ||
          v.message.toLowerCase().includes(searchLower) ||
          v.location?.net?.toLowerCase().includes(searchLower) ||
          v.location?.component?.toLowerCase().includes(searchLower)
        );
      }
      return true;
    });

    // Sort
    const severityOrder = { error: 0, warning: 1, info: 2 };
    result.sort((a: Violation, b: Violation) => {
      if (sortBy === 'severity') {
        return severityOrder[a.severity] - severityOrder[b.severity];
      } else if (sortBy === 'category') {
        return a.category.localeCompare(b.category);
      } else {
        return a.rule_name.localeCompare(b.rule_name);
      }
    });

    return result;
  }, [violations, filters, sortBy]);

  // Violation counts by severity
  const counts = useMemo(() => {
    return {
      error: violations.filter((v: Violation) => v.severity === 'error').length,
      warning: violations.filter((v: Violation) => v.severity === 'warning').length,
      info: violations.filter((v: Violation) => v.severity === 'info').length,
      total: violations.length,
    };
  }, [violations]);

  const handleSeverityToggle = (severity: string) => {
    setFilters((prev) => ({
      ...prev,
      severity: prev.severity.includes(severity)
        ? prev.severity.filter((s) => s !== severity)
        : [...prev.severity, severity],
    }));
  };

  const handleCategoryToggle = (category: string) => {
    setFilters((prev) => ({
      ...prev,
      category: prev.category.includes(category)
        ? prev.category.filter((c) => c !== category)
        : [...prev.category, category],
    }));
  };

  const handleLocate = (violation: Violation) => {
    // Emit event for layout viewer to highlight location
    if (violation.location) {
      const event = new CustomEvent('locateViolation', {
        detail: {
          violationId: violation.id,
          x: violation.location.x,
          y: violation.location.y,
          layer: violation.location.layer,
          net: violation.location.net,
          component: violation.location.component,
        },
      });
      window.dispatchEvent(event);
    }
  };

  if (isLoading) {
    return <div className="loading">Loading violations...</div>;
  }

  if (error) {
    return <div className="error">Failed to load violations</div>;
  }

  return (
    <div className="violations-panel">
      <div className="mb-3">
        <Link to={`/projects/${projectId}`} className="btn btn-secondary">
          ← Back to Project
        </Link>
      </div>

      <div className="card mb-3">
        <div className="flex justify-between items-center">
          <div>
            <h1>Design Violations</h1>
            <p className="text-muted">
              Layout #{layoutId} - {counts.total} total violations
            </p>
          </div>
          <button
            className={`btn ${showViewer ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setShowViewer(!showViewer)}
          >
            {showViewer ? 'Hide Viewer' : 'Show Viewer'}
          </button>
        </div>
      </div>

      {/* PCB Viewer */}
      {showViewer && pcbData && (
        <div className="card mb-3" style={{ height: '400px', position: 'relative' }}>
          {/* Highlighted net indicator */}
          {highlightedNet && (
            <div style={{
              position: 'absolute',
              top: '8px',
              left: '8px',
              zIndex: 10,
              background: 'rgba(0, 255, 136, 0.9)',
              color: '#000',
              padding: '4px 12px',
              borderRadius: '4px',
              fontFamily: 'monospace',
              fontSize: '14px',
              fontWeight: 'bold',
              boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
            }}>
              Highlighting: {highlightedNet}
            </div>
          )}
          <PCBViewer
            data={{
              ...pcbData,
              violations: viewerViolations,
            }}
            selectedViolation={selectedViolation ? String(selectedViolation.id) : (hoveredViolation ? String(hoveredViolation.id) : null)}
            onViolationClick={(v: { id: string }) => {
              const violation = violations.find((viol: Violation) => String(viol.id) === v.id);
              if (violation) setSelectedViolation(violation);
            }}
            className="h-full"
          />
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div
          className={`card summary-card ${filters.severity.includes('error') ? 'active' : 'dimmed'}`}
          onClick={() => handleSeverityToggle('error')}
          style={{ borderLeft: `4px solid ${SEVERITY_COLORS.error}` }}
        >
          <div className="count" style={{ color: SEVERITY_COLORS.error }}>
            {counts.error}
          </div>
          <div className="label">Errors</div>
        </div>

        <div
          className={`card summary-card ${filters.severity.includes('warning') ? 'active' : 'dimmed'}`}
          onClick={() => handleSeverityToggle('warning')}
          style={{ borderLeft: `4px solid ${SEVERITY_COLORS.warning}` }}
        >
          <div className="count" style={{ color: SEVERITY_COLORS.warning }}>
            {counts.warning}
          </div>
          <div className="label">Warnings</div>
        </div>

        <div
          className={`card summary-card ${filters.severity.includes('info') ? 'active' : 'dimmed'}`}
          onClick={() => handleSeverityToggle('info')}
          style={{ borderLeft: `4px solid ${SEVERITY_COLORS.info}` }}
        >
          <div className="count" style={{ color: SEVERITY_COLORS.info }}>
            {counts.info}
          </div>
          <div className="label">Info</div>
        </div>

        <div className="card summary-card" style={{ borderLeft: '4px solid #6c757d' }}>
          <div className="count">{filteredViolations.length}</div>
          <div className="label">Showing</div>
        </div>
      </div>

      {/* Filters */}
      <div className="card mb-3">
        <div className="flex gap-4 items-center flex-wrap">
          {/* Category Filters */}
          <div className="filter-group">
            <label className="filter-label">Category:</label>
            <div className="flex gap-2">
              {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                <button
                  key={key}
                  className={`btn btn-sm ${filters.category.includes(key) ? 'btn-primary' : 'btn-outline'}`}
                  onClick={() => handleCategoryToggle(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Search */}
          <div className="filter-group flex-grow">
            <label className="filter-label">Search:</label>
            <input
              type="text"
              className="form-control"
              placeholder="Search violations..."
              value={filters.search}
              onChange={(e) => setFilters((prev) => ({ ...prev, search: e.target.value }))}
            />
          </div>

          {/* Sort */}
          <div className="filter-group">
            <label className="filter-label">Sort by:</label>
            <select
              className="form-control"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
            >
              <option value="severity">Severity</option>
              <option value="category">Category</option>
              <option value="rule_name">Rule Name</option>
            </select>
          </div>
        </div>
      </div>

      {/* Violations List */}
      <div className="violations-container">
        <div className="violations-list">
          {filteredViolations.length === 0 ? (
            <div className="card text-center text-muted">
              No violations match the current filters
            </div>
          ) : (
            filteredViolations.map((violation: Violation) => (
              <div
                key={violation.id}
                className={`violation-item card ${selectedViolation?.id === violation.id ? 'selected' : ''} ${hoveredViolation?.id === violation.id ? 'hovered' : ''}`}
                onClick={() => setSelectedViolation(violation)}
                onMouseEnter={() => setHoveredViolation(violation)}
                onMouseLeave={() => setHoveredViolation(null)}
              >
                <div className="flex items-start gap-3">
                  {/* Severity Icon */}
                  <div
                    className="severity-indicator"
                    style={{ backgroundColor: SEVERITY_COLORS[violation.severity] }}
                    title={violation.severity.toUpperCase()}
                  />

                  {/* Content */}
                  <div className="flex-grow">
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="badge badge-outline mr-2">
                          {CATEGORY_LABELS[violation.category]}
                        </span>
                        <strong>{violation.rule_name}</strong>
                      </div>
                      {violation.location && (
                        <button
                          className="btn btn-sm btn-outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleLocate(violation);
                          }}
                          title="Locate in layout"
                        >
                          Locate
                        </button>
                      )}
                    </div>
                    <p className="violation-message mt-1">{violation.message}</p>
                    {violation.location && (
                      <div className="violation-location text-sm text-muted mt-1">
                        {violation.location.net && (
                          <span className="net-badge" title="Click to highlight this net in the viewer">
                            {violation.location.net}
                          </span>
                        )}
                        {violation.location.component && (
                          <span className="ml-2">Component: {violation.location.component}</span>
                        )}
                        {violation.location.layer && (
                          <span className="ml-2">Layer: {violation.location.layer}</span>
                        )}
                        {violation.location.x !== undefined && violation.location.y !== undefined && (
                          <span className="ml-2">
                            ({violation.location.x.toFixed(2)}, {violation.location.y.toFixed(2)}) mm
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Detail Panel */}
        {selectedViolation && (
          <div className="violation-detail card">
            <h3>Violation Details</h3>
            <div className="detail-section">
              <div className="flex gap-2 mb-2">
                <span
                  className="badge"
                  style={{ backgroundColor: SEVERITY_COLORS[selectedViolation.severity] }}
                >
                  {selectedViolation.severity.toUpperCase()}
                </span>
                <span className="badge badge-outline">
                  {CATEGORY_LABELS[selectedViolation.category]}
                </span>
              </div>

              <h4>{selectedViolation.rule_name}</h4>
              <p>{selectedViolation.message}</p>

              {selectedViolation.location && (
                <div className="mt-3">
                  <h5>Location</h5>
                  <table className="detail-table">
                    <tbody>
                      {selectedViolation.location.net && (
                        <tr>
                          <td>Net</td>
                          <td>{selectedViolation.location.net}</td>
                        </tr>
                      )}
                      {selectedViolation.location.component && (
                        <tr>
                          <td>Component</td>
                          <td>{selectedViolation.location.component}</td>
                        </tr>
                      )}
                      {selectedViolation.location.layer && (
                        <tr>
                          <td>Layer</td>
                          <td>{selectedViolation.location.layer}</td>
                        </tr>
                      )}
                      {selectedViolation.location.x !== undefined && (
                        <tr>
                          <td>Position</td>
                          <td>
                            ({selectedViolation.location.x.toFixed(3)},{' '}
                            {selectedViolation.location.y?.toFixed(3)}) mm
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              {selectedViolation.details && Object.keys(selectedViolation.details).length > 0 && (
                <div className="mt-3">
                  <h5>Additional Details</h5>
                  <table className="detail-table">
                    <tbody>
                      {Object.entries(selectedViolation.details).map(([key, value]) => (
                        <tr key={key}>
                          <td>{key.replace(/_/g, ' ')}</td>
                          <td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="mt-3">
                <button
                  className="btn btn-primary mr-2"
                  onClick={() => handleLocate(selectedViolation)}
                  disabled={!selectedViolation.location}
                >
                  Locate in Layout
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => setSelectedViolation(null)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        .violations-panel {
          max-width: 1400px;
          margin: 0 auto;
          padding: 1rem;
        }

        .summary-card {
          cursor: pointer;
          transition: opacity 0.2s, transform 0.2s;
          text-align: center;
          padding: 1rem;
        }

        .summary-card:hover {
          transform: translateY(-2px);
        }

        .summary-card.dimmed {
          opacity: 0.5;
        }

        .summary-card .count {
          font-size: 2rem;
          font-weight: bold;
        }

        .summary-card .label {
          font-size: 0.875rem;
          color: #6c757d;
        }

        .filter-group {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }

        .filter-label {
          font-weight: 500;
          font-size: 0.875rem;
        }

        .violations-container {
          display: grid;
          grid-template-columns: 1fr 400px;
          gap: 1rem;
        }

        @media (max-width: 1024px) {
          .violations-container {
            grid-template-columns: 1fr;
          }
        }

        .violations-list {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          max-height: 70vh;
          overflow-y: auto;
        }

        .violation-item {
          cursor: pointer;
          transition: border-color 0.2s, box-shadow 0.2s;
          padding: 0.75rem;
        }

        .violation-item:hover {
          border-color: #0d6efd;
        }

        .violation-item.selected {
          border-color: #0d6efd;
          box-shadow: 0 0 0 2px rgba(13, 110, 253, 0.25);
        }

        .violation-item.hovered {
          border-color: #00ff88;
          background-color: rgba(0, 255, 136, 0.05);
        }

        .violation-item .net-badge {
          background-color: #e0f7e9;
          color: #00aa55;
          padding: 2px 6px;
          border-radius: 3px;
          font-size: 0.75rem;
          font-family: monospace;
        }

        .severity-indicator {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          flex-shrink: 0;
          margin-top: 4px;
        }

        .violation-message {
          margin: 0;
          color: #495057;
        }

        .violation-location {
          font-family: monospace;
        }

        .violation-detail {
          position: sticky;
          top: 1rem;
          max-height: 70vh;
          overflow-y: auto;
        }

        .detail-section h5 {
          font-size: 0.875rem;
          font-weight: 600;
          color: #6c757d;
          margin-bottom: 0.5rem;
        }

        .detail-table {
          width: 100%;
          font-size: 0.875rem;
        }

        .detail-table td {
          padding: 0.25rem 0.5rem;
          border-bottom: 1px solid #e9ecef;
        }

        .detail-table td:first-child {
          font-weight: 500;
          color: #6c757d;
          width: 40%;
        }
      `}</style>
    </div>
  );
}
