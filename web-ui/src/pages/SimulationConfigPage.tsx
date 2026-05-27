import React, { useState, useEffect } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { simulationsApi, aiApi, highSpeedApi } from '../api/client';

// Interface type styling
const INTERFACE_COLORS: Record<string, { bg: string; text: string; icon: string }> = {
  ddr4: { bg: '#e3f2fd', text: '#1565c0', icon: '🧠' },
  ddr5: { bg: '#e3f2fd', text: '#0d47a1', icon: '🧠' },
  lpddr4: { bg: '#e8f5e9', text: '#2e7d32', icon: '🧠' },
  usb2: { bg: '#fff3e0', text: '#e65100', icon: '🔌' },
  usb3: { bg: '#fff3e0', text: '#bf360c', icon: '⚡' },
  pcie_gen3: { bg: '#fce4ec', text: '#c2185b', icon: '🚀' },
  pcie_gen4: { bg: '#fce4ec', text: '#880e4f', icon: '🚀' },
  pcie_gen5: { bg: '#fce4ec', text: '#4a148c', icon: '🚀' },
  ethernet_1g: { bg: '#e0f7fa', text: '#00695c', icon: '🌐' },
  ethernet_10g: { bg: '#e0f7fa', text: '#004d40', icon: '🌐' },
  hdmi: { bg: '#f3e5f5', text: '#7b1fa2', icon: '📺' },
  displayport: { bg: '#f3e5f5', text: '#6a1b9a', icon: '🖥️' },
  sata: { bg: '#efebe9', text: '#4e342e', icon: '💾' },
};

function formatFrequency(hz: number): string {
  if (hz >= 1e9) return `${(hz / 1e9).toFixed(1)} GHz`;
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(1)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz} Hz`;
}

interface DetectedInterface {
  type: string;
  description?: string;
  confidence: number;
  nets: string[];
  frequency_range_hz: number[];
  target_impedance_ohm: number;
}

export default function SimulationConfigPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const layoutId = searchParams.get('layoutId');

  const [useAI, setUseAI] = useState(false);
  const [aiDescription, setAiDescription] = useState('');
  const [selectedInterface, setSelectedInterface] = useState<string | null>(null);
  const [config, setConfig] = useState({
    name: '',
    frequency_start_hz: 1e6,
    frequency_stop_hz: 6e9,
    frequency_points: 201,
    ports: '1,2',
    solver_type: 'analytical' as 'analytical' | 'openems',
  });

  // Fetch detected high-speed interfaces
  const { data: interfacesData, isLoading: interfacesLoading } = useQuery({
    queryKey: ['interfaces', layoutId],
    queryFn: () => highSpeedApi.detectInterfaces(Number(layoutId)),
    enabled: !!layoutId,
  });

  // Update frequency range when interface is selected
  useEffect(() => {
    if (selectedInterface && interfacesData?.interfaces) {
      const iface = interfacesData.interfaces.find(
        (i: DetectedInterface) => i.type === selectedInterface
      );
      if (iface) {
        setConfig((prev) => ({
          ...prev,
          frequency_start_hz: iface.frequency_range_hz[0],
          frequency_stop_hz: iface.frequency_range_hz[1],
          name: prev.name || `${iface.type.toUpperCase()} Analysis`,
        }));
      }
    }
  }, [selectedInterface, interfacesData]);

  const createMutation = useMutation({
    mutationFn: async () => {
      const simConfig = await simulationsApi.create({
        project_id: Number(projectId),
        layout_id: Number(layoutId),
        name: config.name || undefined,
        frequency_start_hz: config.frequency_start_hz,
        frequency_stop_hz: config.frequency_stop_hz,
        frequency_points: config.frequency_points,
        ports: config.ports.split(',').map((p) => parseInt(p.trim())),
        solver_settings: {
          solver_type: config.solver_type,
          interface_type: selectedInterface || undefined,
        },
      });
      return simulationsApi.run(simConfig.id);
    },
    onSuccess: (run) => {
      navigate(`/simulations/runs/${run.id}`);
    },
  });

  const handleAIGenerate = async () => {
    if (!aiDescription.trim()) return;

    try {
      const result = await aiApi.generateConfig({
        project_id: Number(projectId),
        layout_id: Number(layoutId!),
        description: aiDescription,
      });

      if (result.template) {
        const template = result.template;
        setConfig({
          ...config,
          name: config.name || 'AI Generated',
          frequency_start_hz: template.frequency_start_hz || 1e6,
          frequency_stop_hz: template.frequency_stop_hz || 1e9,
          frequency_points: template.frequency_points || 101,
          ports: template.ports ? template.ports.join(',') : '1,2',
        });
        setUseAI(false);
      }
    } catch (error) {
      console.error('AI config generation failed:', error);
    }
  };

  const interfaces: DetectedInterface[] = interfacesData?.interfaces || [];

  return (
    <div>
      <div className="mb-3">
        <Link to={`/projects/${projectId}`} className="btn btn-secondary">
          ← Back to Project
        </Link>
      </div>

      <div className="card mb-3">
        <h1>Configure EM Simulation</h1>
        <p className="text-muted">
          Set up electromagnetic simulation parameters for your PCB layout
        </p>
      </div>

      {/* Detected Interfaces Section */}
      {layoutId && (
        <div className="card mb-3">
          <h2>Detected High-Speed Interfaces</h2>
          {interfacesLoading ? (
            <p className="text-muted">Analyzing layout for high-speed interfaces...</p>
          ) : interfaces.length > 0 ? (
            <>
              <p className="text-muted mb-2">
                Click an interface to auto-configure frequency range for optimal analysis
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {interfaces.map((iface: DetectedInterface) => {
                  const colors = INTERFACE_COLORS[iface.type] || {
                    bg: '#f5f5f5',
                    text: '#333',
                    icon: '📡',
                  };
                  const isSelected = selectedInterface === iface.type;
                  return (
                    <button
                      key={iface.type}
                      onClick={() =>
                        setSelectedInterface(isSelected ? null : iface.type)
                      }
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 14px',
                        borderRadius: '20px',
                        border: isSelected
                          ? `2px solid ${colors.text}`
                          : '2px solid transparent',
                        backgroundColor: colors.bg,
                        color: colors.text,
                        fontWeight: 500,
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        boxShadow: isSelected
                          ? '0 2px 8px rgba(0,0,0,0.15)'
                          : 'none',
                      }}
                    >
                      <span>{colors.icon}</span>
                      <span>{iface.type.toUpperCase()}</span>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          opacity: 0.7,
                        }}
                      >
                        ({Math.round(iface.confidence * 100)}%)
                      </span>
                    </button>
                  );
                })}
              </div>

              {selectedInterface && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '12px',
                    backgroundColor: '#f8f9fa',
                    borderRadius: '8px',
                    borderLeft: '4px solid #2196f3',
                  }}
                >
                  {(() => {
                    const iface = interfaces.find(
                      (i: DetectedInterface) => i.type === selectedInterface
                    );
                    if (!iface) return null;
                    return (
                      <>
                        <p style={{ margin: 0, fontWeight: 500 }}>
                          {iface.description || iface.type.toUpperCase()}
                        </p>
                        <p
                          style={{
                            margin: '4px 0 0 0',
                            fontSize: '0.9rem',
                            color: '#666',
                          }}
                        >
                          Frequency: {formatFrequency(iface.frequency_range_hz[0])} -{' '}
                          {formatFrequency(iface.frequency_range_hz[1])} | Target Z₀:{' '}
                          {iface.target_impedance_ohm}Ω | {iface.nets.length} nets
                          detected
                        </p>
                      </>
                    );
                  })()}
                </div>
              )}
            </>
          ) : (
            <p className="text-muted">
              No high-speed interfaces detected. You can still configure manual
              frequency settings below.
            </p>
          )}
        </div>
      )}

      <div className="card mb-3">
        <div className="flex-between mb-3">
          <h2>Configuration Method</h2>
          <button
            className="btn btn-secondary"
            onClick={() => setUseAI(!useAI)}
          >
            {useAI ? 'Manual Config' : 'AI Assistant'}
          </button>
        </div>

        {useAI ? (
          <div>
            <div className="form-group">
              <label>Describe Your Simulation Needs</label>
              <textarea
                className="form-control"
                value={aiDescription}
                onChange={(e) => setAiDescription(e.target.value)}
                placeholder="e.g., RF design from 1-10 GHz, high-speed digital, impedance matching analysis"
                rows={4}
              />
            </div>
            <button
              className="btn btn-primary"
              onClick={handleAIGenerate}
              disabled={!aiDescription.trim()}
            >
              Generate Configuration
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
          >
            {/* Solver Type Selection */}
            <div className="form-group">
              <label>Simulation Solver</label>
              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '12px 16px',
                    border:
                      config.solver_type === 'analytical'
                        ? '2px solid #4caf50'
                        : '2px solid #ddd',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    backgroundColor:
                      config.solver_type === 'analytical' ? '#e8f5e9' : '#fff',
                  }}
                >
                  <input
                    type="radio"
                    name="solver_type"
                    value="analytical"
                    checked={config.solver_type === 'analytical'}
                    onChange={() =>
                      setConfig({ ...config, solver_type: 'analytical' })
                    }
                  />
                  <div>
                    <div style={{ fontWeight: 500 }}>⚡ Analytical</div>
                    <div style={{ fontSize: '0.8rem', color: '#666' }}>
                      Fast ABCD matrix calculation (~seconds)
                    </div>
                  </div>
                </label>
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '12px 16px',
                    border:
                      config.solver_type === 'openems'
                        ? '2px solid #2196f3'
                        : '2px solid #ddd',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    backgroundColor:
                      config.solver_type === 'openems' ? '#e3f2fd' : '#fff',
                  }}
                >
                  <input
                    type="radio"
                    name="solver_type"
                    value="openems"
                    checked={config.solver_type === 'openems'}
                    onChange={() =>
                      setConfig({ ...config, solver_type: 'openems' })
                    }
                  />
                  <div>
                    <div style={{ fontWeight: 500 }}>🔬 OpenEMS FDTD</div>
                    <div style={{ fontSize: '0.8rem', color: '#666' }}>
                      Full-wave simulation (~minutes to hours)
                    </div>
                  </div>
                </label>
              </div>
            </div>

            <div className="form-group">
              <label>Simulation Name (Optional)</label>
              <input
                type="text"
                className="form-control"
                value={config.name}
                onChange={(e) => setConfig({ ...config, name: e.target.value })}
                placeholder="e.g., Baseline impedance check"
              />
            </div>

            <div className="grid grid-2">
              <div className="form-group">
                <label>Start Frequency (Hz)</label>
                <input
                  type="number"
                  className="form-control"
                  value={config.frequency_start_hz}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      frequency_start_hz: Number(e.target.value),
                    })
                  }
                  min="1"
                  step="any"
                />
                <p className="text-muted text-small mt-1">
                  {formatFrequency(config.frequency_start_hz)}
                </p>
              </div>

              <div className="form-group">
                <label>Stop Frequency (Hz)</label>
                <input
                  type="number"
                  className="form-control"
                  value={config.frequency_stop_hz}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      frequency_stop_hz: Number(e.target.value),
                    })
                  }
                  min="1"
                  step="any"
                />
                <p className="text-muted text-small mt-1">
                  {formatFrequency(config.frequency_stop_hz)}
                </p>
              </div>
            </div>

            <div className="form-group">
              <label>Frequency Points</label>
              <input
                type="number"
                className="form-control"
                value={config.frequency_points}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    frequency_points: Number(e.target.value),
                  })
                }
                min="10"
                max="1000"
              />
              <p className="text-muted text-small mt-1">
                More points = higher resolution but longer simulation time
              </p>
            </div>

            <div className="form-group">
              <label>Port Numbers (comma-separated)</label>
              <input
                type="text"
                className="form-control"
                value={config.ports}
                onChange={(e) => setConfig({ ...config, ports: e.target.value })}
                placeholder="e.g., 1,2"
              />
            </div>

            <button
              type="submit"
              className="btn btn-success"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending
                ? 'Starting Simulation...'
                : `Run ${config.solver_type === 'analytical' ? 'Analytical' : 'OpenEMS'} Simulation`}
            </button>

            {createMutation.isError && (
              <p style={{ color: '#d32f2f', marginTop: '12px' }}>
                Error starting simulation. Please check your configuration.
              </p>
            )}
          </form>
        )}
      </div>

      {/* Interface-specific tips */}
      {selectedInterface && config.solver_type === 'analytical' && (
        <div className="card mb-3">
          <h2>Analysis Tips for {selectedInterface.toUpperCase()}</h2>
          {selectedInterface.startsWith('ddr') && (
            <ul style={{ margin: 0, paddingLeft: '20px', lineHeight: 1.8 }}>
              <li>
                Check S21 insertion loss at Nyquist frequency (data rate / 2)
              </li>
              <li>Verify return loss S11 &lt; -10dB across frequency range</li>
              <li>Ensure length matching for DQ/DQS pairs (&lt;5ps skew)</li>
            </ul>
          )}
          {selectedInterface.startsWith('usb') && (
            <ul style={{ margin: 0, paddingLeft: '20px', lineHeight: 1.8 }}>
              <li>Differential impedance target: 90Ω ±10%</li>
              <li>Check for common-mode conversion (S31, S41)</li>
              <li>Verify eye diagram at receiver with channel model</li>
            </ul>
          )}
          {selectedInterface.startsWith('pcie') && (
            <ul style={{ margin: 0, paddingLeft: '20px', lineHeight: 1.8 }}>
              <li>Differential impedance target: 85Ω ±10%</li>
              <li>Insertion loss budget: typically &lt;3-5dB at Nyquist</li>
              <li>AC coupling capacitors affect low-frequency response</li>
            </ul>
          )}
          {selectedInterface.startsWith('ethernet') && (
            <ul style={{ margin: 0, paddingLeft: '20px', lineHeight: 1.8 }}>
              <li>Differential impedance target: 100Ω ±10%</li>
              <li>Check transformer coupling effects</li>
              <li>Verify EMC compliance with return loss specs</li>
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
