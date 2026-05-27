import axios from 'axios';

// Prefer build-time VITE_API_URL; fallback to backend port inferred from current host.
const inferredApi =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8003/api/v1`
    : '/api/v1';
const API_BASE_URL = import.meta.env.VITE_API_URL || inferredApi;

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface Project {
  id: number;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
}

export interface PCBLayout {
  id: number;
  project_id: number;
  layout_name: string;
  filename: string;
  file_path: string;
  file_size_bytes?: number;
  file_type?: string;
  layout_metadata?: string;
  version: number;
  created_at: string;
  is_parsed?: boolean;
  parsed_at?: string | null;
  parse_error?: string | null;
  board_width_mm?: number | null;
  board_height_mm?: number | null;
  board_thickness_mm?: number | null;
  layer_count?: number | null;
}

export interface SimulationConfig {
  id: number;
  project_id: number;
  layout_id: number;
  name?: string;
  frequency_start_hz: number;
  frequency_stop_hz: number;
  frequency_points?: number;
  ports?: number[];
  mesh_settings?: any;
  boundary_conditions?: any;
  solver_settings?: any;
  created_at: string;
}

export interface SimulationRun {
  id: number;
  simulation_id: number;
  status: string;
  progress_percent?: number;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface ResultSet {
  id: number;
  run_id: number;
  result_type: string;
  data?: any;
  file_path?: string;
  created_at: string;
}

// PCB Viewer data types
export interface PCBViewerComponent {
  id: number;
  reference: string;
  part_number?: string;
  value?: string;
  package?: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
  layer: string;
  width_mm?: number;
  height_mm?: number;
}

export interface PCBViewerNet {
  id: number;
  name: string;
  net_class?: string;
  is_differential?: boolean;
}

export interface PCBViewerTrace {
  id: number;
  net_id?: number;
  net_name?: string;
  layer: string;
  layer_number?: number;
  width_mm: number;
  length_mm?: number;
  geometry: Array<{ x: number; y: number }>;
}

export interface PCBViewerVia {
  id: number;
  net_id?: number;
  net_name?: string;
  via_type: string;
  x_mm: number;
  y_mm: number;
  drill_diameter_mm: number;
  pad_diameter_mm: number;
  start_layer?: string;
  end_layer?: string;
}

export interface PCBViewerLayer {
  id: number;
  name: string;
  layer_number: number;
  layer_type: string;
  is_copper: boolean;
  thickness_mm?: number;
}

export interface PCBViewerViolation {
  id: number;
  category: string;
  rule_name?: string;
  severity: string;
  message: string;
  location_x_mm?: number;
  location_y_mm?: number;
  affected_net?: string;
  affected_component?: string;
  layer?: string;
  bounding_box?: any;
}

export interface PCBViewerData {
  layout: {
    id: number;
    name: string;
    board_width_mm?: number;
    board_height_mm?: number;
    layer_count?: number;
    is_parsed: boolean;
  };
  layer_stack: PCBViewerLayer[];
  components: PCBViewerComponent[];
  nets: PCBViewerNet[];
  traces: PCBViewerTrace[];
  vias: PCBViewerVia[];
  violations: PCBViewerViolation[];
  summary: {
    component_count: number;
    net_count: number;
    trace_count: number;
    via_count: number;
    violation_count: number;
  };
}

// Projects API
export const projectsApi = {
  list: () => apiClient.get<Project[]>('/projects/').then((r: any) => r.data),

  get: (id: number) => apiClient.get<Project>(`/projects/${id}`).then((r: any) => r.data),

  create: (data: { name: string; description?: string }) =>
    apiClient.post<Project>('/projects/', data).then((r: any) => r.data),

  delete: (id: number) =>
    apiClient.delete<any>(`/projects/${id}`).then((r: any) => r.data),

  listLayouts: (projectId: number) =>
    apiClient.get<PCBLayout[]>(`/projects/${projectId}/layouts`).then((r: any) => r.data),

  uploadLayout: (projectId: number, file: File, layoutName?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (layoutName) {
      formData.append('layout_name', layoutName);
    }

    return apiClient.post<PCBLayout>(
      `/projects/${projectId}/layouts/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    ).then((r: any) => r.data);
  },

  deleteLayout: (projectId: number, layoutId: number) =>
    apiClient.delete<any>(`/projects/${projectId}/layouts/${layoutId}`).then((r: any) => r.data),

  // Get comprehensive PCB viewer data
  getViewerData: (projectId: number, layoutId: number) =>
    apiClient.get<PCBViewerData>(`/projects/${projectId}/layouts/${layoutId}/viewer-data`).then((r: any) => r.data),
};

// Simulations API
export const simulationsApi = {
  create: (data: Partial<SimulationConfig>) =>
    apiClient.post<SimulationConfig>('/simulations/', data).then((r: any) => r.data),
  
  get: (id: number) =>
    apiClient.get<SimulationConfig>(`/simulations/${id}`).then((r: any) => r.data),
  
  run: (simulationId: number) =>
    apiClient.post<SimulationRun>(`/simulations/${simulationId}/run`).then((r: any) => r.data),
  
  getRun: (runId: number) =>
    apiClient.get<SimulationRun>(`/simulations/runs/${runId}`).then((r: any) => r.data),
  
  getResults: (runId: number) =>
    apiClient.get<ResultSet[]>(`/simulations/runs/${runId}/results`).then((r: any) => r.data),
  
  getMetrics: (runId: number) =>
    apiClient.get<any>(`/simulations/runs/${runId}/metrics`).then((r: any) => r.data),
  
  getFieldSummary: (runId: number) =>
    apiClient.get<any>(`/simulations/runs/${runId}/field-summary`).then((r: any) => r.data),
  
  exportTouchstone: (runId: number) =>
    apiClient.get<string>(`/simulations/runs/${runId}/export/touchstone`).then((r: any) => r.data),

  // Get all simulations for a layout
  getByLayout: (layoutId: number) =>
    apiClient.get<any>(`/simulations/by-layout/${layoutId}`).then((r: any) => r.data),

  // Get integrated analysis (SI/PI combined with EM)
  getIntegratedAnalysis: (runId: number) =>
    apiClient.get<any>(`/simulations/runs/${runId}/integrated-analysis`).then((r: any) => r.data),
};

// Analysis API
export const analysisApi = {
  // RF/SI Analysis
  calculateImpedance: (data: {
    line_type: string;
    trace_width_mm: number;
    height_mm: number;
    dielectric_constant?: number;
    spacing_mm?: number;
  }) => apiClient.post<any>('/analysis/rf-si/impedance', data).then((r: any) => r.data),

  analyzeCrosstalk: (data: {
    aggressor_width_mm: number;
    victim_width_mm: number;
    spacing_mm: number;
    parallel_length_mm: number;
    height_mm: number;
    dielectric_constant?: number;
  }) => apiClient.post<any>('/analysis/rf-si/crosstalk', data).then((r: any) => r.data),

  analyzeVia: (data: {
    drill_mm: number;
    pad_mm: number;
    antipad_mm: number;
    stackup_height_mm: number;
    dielectric_constant?: number;
  }) => apiClient.post<any>('/analysis/rf-si/via', data).then((r: any) => r.data),

  analyzeDiffPair: (data: {
    positive_width_mm: number;
    positive_length_mm: number;
    negative_width_mm: number;
    negative_length_mm: number;
    spacing_mm: number;
    height_mm: number;
    dielectric_constant?: number;
  }) => apiClient.post<any>('/analysis/rf-si/differential-pair', data).then((r: any) => r.data),

  // EMC Analysis
  analyzeGrounding: (data: {
    board_width_mm: number;
    board_height_mm: number;
    planes: any[];
    max_frequency_mhz?: number;
  }) => apiClient.post<any>('/analysis/emc/grounding', data).then((r: any) => r.data),

  analyzeShielding: (data: {
    material: string;
    thickness_mm: number;
    frequency_mhz: number;
  }) => apiClient.post<any>('/analysis/emc/shielding', data).then((r: any) => r.data),

  // DFM Analysis
  analyzeSolderPaste: (data: {
    component_ref: string;
    package_type: string;
    pads: any[];
  }) => apiClient.post<any>('/analysis/dfm/solder-paste', data).then((r: any) => r.data),

  analyzePlacement: (data: {
    components: any[];
    board_width_mm: number;
    board_height_mm: number;
    keepouts?: any[];
  }) => apiClient.post<any>('/analysis/dfm/placement', data).then((r: any) => r.data),

  // DRC - Run full design rule check
  runDRC: (layoutId: number) =>
    apiClient.post<any>(`/analysis/drc/${layoutId}`).then((r: any) => r.data),

  // Get violations for a layout
  getViolations: (layoutId: number) =>
    apiClient.get<any[]>(`/layouts/${layoutId}/violations`).then((r: any) => r.data),
};

// Layouts API
export const layoutsApi = {
  // Get layout details
  get: (layoutId: number) =>
    apiClient.get<PCBLayout>(`/layouts/${layoutId}`).then((r: any) => r.data),

  // Get parsed PCB data for viewer
  getPCBData: (layoutId: number) =>
    apiClient.get<any>(`/layouts/${layoutId}/pcb-data`).then((r: any) => r.data),
};

// AI API
export const aiApi = {
  reviewLayout: (data: { project_id: number; layout_id: number; context?: string }) =>
    apiClient.post<any>('/ai/pcb/review', data).then((r: any) => r.data),
  
  identifyHotspots: (layoutId: number) =>
    apiClient.post<any>(`/ai/pcb/hotspots?layout_id=${layoutId}`).then((r: any) => r.data),
  
  generateConfig: (data: { project_id: number; layout_id: number; description: string }) =>
    apiClient.post<any>('/ai/simulation/config', data).then((r: any) => r.data),
  
  validateConfig: (config: any) =>
    apiClient.post<any>('/ai/simulation/validate', config).then((r: any) => r.data),
  
  estimateResources: (config: any) =>
    apiClient.post<any>('/ai/simulation/estimate', config).then((r: any) => r.data),
  
  interpretResults: (data: { run_id: number; focus?: string }) =>
    apiClient.post<any>('/ai/simulation/interpret', data).then((r: any) => r.data),
  
  compareDesigns: (runId1: number, runId2: number) =>
    apiClient.post<any>(`/ai/simulation/compare?run_id_1=${runId1}&run_id_2=${runId2}`).then((r: any) => r.data),
};

// Rules API - Design rules and waivers management
export const rulesApi = {
  // Rule check results
  getViolations: (layoutId: number) =>
    apiClient.get<any>(`/rules/layouts/${layoutId}/violations`).then((r: any) => r.data),
  
  runCheck: (layoutId: number, ruleSetIds?: string[]) =>
    apiClient.post<any>(`/rules/layouts/${layoutId}/check`, { rule_set_ids: ruleSetIds }).then((r: any) => r.data),
  
  exportViolations: (layoutId: number, format: 'csv' | 'json' | 'pdf') =>
    apiClient.get<any>(`/rules/layouts/${layoutId}/violations/export?format=${format}`, {
      responseType: format === 'pdf' ? 'blob' : 'text',
    }).then((r: any) => r.data),

  // Custom rules
  getCustomRules: (projectId: number) =>
    apiClient.get<any>(`/rules/projects/${projectId}/custom-rules`).then((r: any) => r.data),
  
  createCustomRule: (projectId: number, rule: any) =>
    apiClient.post<any>(`/rules/projects/${projectId}/custom-rules`, rule).then((r: any) => r.data),
  
  updateCustomRule: (projectId: number, ruleId: string, rule: any) =>
    apiClient.put<any>(`/rules/projects/${projectId}/custom-rules/${ruleId}`, rule).then((r: any) => r.data),
  
  deleteCustomRule: (projectId: number, ruleId: string) =>
    apiClient.delete<any>(`/rules/projects/${projectId}/custom-rules/${ruleId}`).then((r: any) => r.data),

  // Waivers
  getWaivers: (projectId: number) =>
    apiClient.get<any>(`/rules/projects/${projectId}/waivers`).then((r: any) => r.data),
  
  addWaiver: (layoutId: number, ruleId: string, reason: string) =>
    apiClient.post<any>(`/rules/layouts/${layoutId}/waivers`, { rule_id: ruleId, reason }).then((r: any) => r.data),
  
  updateWaiver: (projectId: number, waiverId: string, status: string) =>
    apiClient.patch<any>(`/rules/projects/${projectId}/waivers/${waiverId}`, { status }).then((r: any) => r.data),

  // Standard rule sets
  getAvailableRuleSets: () =>
    apiClient.get<any>('/rules/rule-sets').then((r: any) => r.data),
  
  getRuleSetDetails: (ruleSetId: string) =>
    apiClient.get<any>(`/rules/rule-sets/${ruleSetId}`).then((r: any) => r.data),
};

// Thermal API - Thermal analysis and visualization
export const thermalApi = {
  getThermalAnalysis: (layoutId: number) =>
    apiClient.get<any>(`/analysis/thermal/${layoutId}`).then((r: any) => r.data),

  runThermalAnalysis: (layoutId: number, options?: any) =>
    apiClient.post<any>(`/analysis/thermal/${layoutId}/analyze`, options).then((r: any) => r.data),

  getHotspots: (layoutId: number) =>
    apiClient.get<any>(`/analysis/thermal/${layoutId}/hotspots`).then((r: any) => r.data),

  getThermalVias: (layoutId: number) =>
    apiClient.get<any>(`/analysis/thermal/${layoutId}/thermal-vias`).then((r: any) => r.data),

  getCopperCoverage: (layoutId: number) =>
    apiClient.get<any>(`/analysis/thermal/${layoutId}/copper-coverage`).then((r: any) => r.data),
};

// High-Speed Interface Analysis API
export interface DetectedInterface {
  type: string;
  description?: string;
  confidence: number;
  nets: string[];
  frequency_range_hz: number[];
  target_impedance_ohm: number;
}

export interface InterfaceSParamResult {
  interface_type: string;
  description: string;
  confidence: number;
  nets: string[];
  frequencies_hz: number[];
  frequencies_ghz: number[];
  s11_db: number[];
  s21_db: number[];
  traces_analyzed: number;
  avg_impedance_ohm: number;
  target_impedance_ohm: number;
}

export const highSpeedApi = {
  // Detect high-speed interfaces in a layout
  detectInterfaces: (layoutId: number) =>
    apiClient.get<{
      layout_id: number;
      interfaces: DetectedInterface[];
      total_nets: number;
    }>(`/analysis/high-speed/interfaces/${layoutId}`).then((r: any) => r.data),

  // Calculate S-parameters for a specific interface
  calculateInterfaceSParams: (layoutId: number, data: {
    interface_type: string;
    frequency_start_hz?: number;
    frequency_stop_hz?: number;
    frequency_points?: number;
    nets?: string[];
  }) =>
    apiClient.post<InterfaceSParamResult>(`/analysis/high-speed/sparams/${layoutId}`, data).then((r: any) => r.data),

  // Calculate S-parameters for all detected interfaces
  calculateAllSParams: (layoutId: number, params?: {
    frequency_start_hz?: number;
    frequency_stop_hz?: number;
    frequency_points?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.frequency_start_hz) query.append('frequency_start_hz', params.frequency_start_hz.toString());
    if (params?.frequency_stop_hz) query.append('frequency_stop_hz', params.frequency_stop_hz.toString());
    if (params?.frequency_points) query.append('frequency_points', params.frequency_points.toString());
    return apiClient.get<{
      layout_id: number;
      analysis_type: string;
      interfaces: Record<string, any>;
    }>(`/analysis/high-speed/sparams/${layoutId}/all?${query.toString()}`).then((r: any) => r.data);
  },

  // List supported interface types
  listInterfaceTypes: () =>
    apiClient.get<{
      supported_interfaces: Array<{
        type: string;
        description: string;
        frequency_range_hz: number[];
        target_impedance_ohm: number;
        pattern_count: number;
      }>;
    }>('/analysis/high-speed/interface-types').then((r: any) => r.data),

  // Get interface summary for a layout
  getInterfaceSummary: (layoutId: number) =>
    apiClient.get<{
      layout_id: number;
      total_interfaces: number;
      interfaces: Array<{
        type: string;
        description?: string;
        confidence: number;
        net_count: number;
        trace_count: number;
        frequency_range_hz: number[];
        target_impedance_ohm: number;
        recommended_action: string;
      }>;
      has_high_speed: boolean;
    }>(`/analysis/high-speed/summary/${layoutId}`).then((r: any) => r.data),
};

// Agent API - Autonomous multi-agent design review orchestrator
export const agentApi = {
  // List available AI models with capabilities and pricing
  getAvailableModels: () =>
    apiClient.get<any>('/agent/models').then((r: any) => r.data),

  // Start autonomous review with orchestrator
  startReview: (layoutId: number, options?: {
    detail_level?: string;
    categories?: string[];
    skip_ai?: boolean;
    include_correlations?: boolean;
    output_formats?: string[];
    model?: string;
    prefer_codex?: boolean;
    prefer_cost_efficiency?: boolean;
    prefer_speed?: boolean;
  }) =>
    apiClient.post<any>(`/agent/review/${layoutId}`, options).then((r: any) => r.data),

  // Get review status (polling)
  getReviewStatus: (reviewId: string) =>
    apiClient.get<any>(`/agent/review/${reviewId}/status`).then((r: any) => r.data),

  // Get complete review results
  getReviewResults: (reviewId: string) =>
    apiClient.get<any>(`/agent/review/${reviewId}/results`).then((r: any) => r.data),

  // Get findings with filtering
  getFindings: (reviewId: string, filters?: {
    category?: string;
    severity?: string;
    limit?: number;
    offset?: number;
  }) => {
    const params = new URLSearchParams();
    if (filters?.category) params.append('category', filters.category);
    if (filters?.severity) params.append('severity', filters.severity);
    if (filters?.limit) params.append('limit', filters.limit.toString());
    if (filters?.offset) params.append('offset', filters.offset.toString());

    return apiClient.get<any>(`/agent/review/${reviewId}/findings?${params.toString()}`).then((r: any) => r.data);
  },

  // Download review report
  getReport: (reviewId: string, format: 'json' | 'html' | 'pdf' = 'html') =>
    apiClient.get<any>(`/agent/review/${reviewId}/report?format=${format}`).then((r: any) => r.data),

  // Cancel running review
  cancelReview: (reviewId: string) =>
    apiClient.delete<any>(`/agent/review/${reviewId}`).then((r: any) => r.data),

  // Quick classification (fast, no full analysis)
  quickClassify: (layoutId: number) =>
    apiClient.post<any>(`/agent/classify/${layoutId}`).then((r: any) => r.data),

  // List recent reviews
  listReviews: (layoutId?: number, status?: string, limit?: number) => {
    const params = new URLSearchParams();
    if (layoutId) params.append('layout_id', layoutId.toString());
    if (status) params.append('status', status);
    if (limit) params.append('limit', limit.toString());

    return apiClient.get<any>(`/agent/reviews?${params.toString()}`).then((r: any) => r.data);
  },

  // Check agent service health
  healthCheck: () =>
    apiClient.get<any>('/agent/health').then((r: any) => r.data),
};

// Schematics API - Schematic file management
export interface Schematic {
  id: number;
  project_id: number;
  filename: string;
  is_parsed: boolean;
  sheet_count?: number;
  title?: string;
  revision?: string;
  designer?: string;
  created_at: string;
  updated_at: string;
}

export interface SchematicComponent {
  id: number;
  reference: string;
  value?: string;
  part_number?: string;
  manufacturer?: string;
  footprint?: string;
  sheet_number: number;
  x_coord: number;
  y_coord: number;
}

export interface SchematicNet {
  id: number;
  net_name: string;
  net_code?: number;
  is_power: boolean;
  is_ground: boolean;
}

export const schematicsApi = {
  // Upload schematic file
  upload: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    return apiClient.post<{ message: string; schematic: Schematic }>(
      `/projects/${projectId}/schematics/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    ).then((r: any) => r.data);
  },

  // List project schematics
  list: (projectId: number) =>
    apiClient.get<Schematic[]>(`/projects/${projectId}/schematics`).then((r: any) => r.data),

  // Get schematic details
  get: (schematicId: number) =>
    apiClient.get<Schematic>(`/schematics/${schematicId}`).then((r: any) => r.data),

  // Get schematic components
  getComponents: (schematicId: number) =>
    apiClient.get<SchematicComponent[]>(`/schematics/${schematicId}/components`).then((r: any) => r.data),

  // Get schematic nets
  getNets: (schematicId: number) =>
    apiClient.get<SchematicNet[]>(`/schematics/${schematicId}/nets`).then((r: any) => r.data),

  // Delete schematic
  delete: (schematicId: number) =>
    apiClient.delete<any>(`/schematics/${schematicId}`).then((r: any) => r.data),

  // Reparse schematic
  reparse: (schematicId: number) =>
    apiClient.post<Schematic>(`/schematics/${schematicId}/reparse`).then((r: any) => r.data),
};

// BOM API - Bill of Materials management
export interface BOM {
  id: number;
  project_id: number;
  filename: string;
  is_parsed: boolean;
  total_items?: number;
  title?: string;
  revision?: string;
  created_at: string;
  updated_at: string;
}

export interface BOMItem {
  id: number;
  line_number: number;
  references: string;
  quantity: number;
  value?: string;
  part_number?: string;
  manufacturer?: string;
  description?: string;
  footprint?: string;
  supplier?: string;
  supplier_part_number?: string;
  unit_price?: number;
  component_type?: string;
}

export interface BOMStatistics {
  total_items: number;
  total_quantity: number;
  component_types: Record<string, { count: number; quantity: number }>;
  total_cost: number;
  missing_part_numbers: number;
}

export const bomApi = {
  // Upload BOM file
  upload: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    return apiClient.post<{ message: string; bom: BOM }>(
      `/projects/${projectId}/boms/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    ).then((r: any) => r.data);
  },

  // List project BOMs
  list: (projectId: number) =>
    apiClient.get<BOM[]>(`/projects/${projectId}/boms`).then((r: any) => r.data),

  // Get BOM details
  get: (bomId: number) =>
    apiClient.get<BOM>(`/boms/${bomId}`).then((r: any) => r.data),

  // Get BOM items
  getItems: (bomId: number, componentType?: string) => {
    const params = componentType ? `?component_type=${componentType}` : '';
    return apiClient.get<BOMItem[]>(`/boms/${bomId}/items${params}`).then((r: any) => r.data);
  },

  // Get BOM statistics
  getStatistics: (bomId: number) =>
    apiClient.get<BOMStatistics>(`/boms/${bomId}/statistics`).then((r: any) => r.data),

  // Get items missing part numbers
  getMissing: (bomId: number) =>
    apiClient.get<BOMItem[]>(`/boms/${bomId}/missing`).then((r: any) => r.data),

  // Delete BOM
  delete: (bomId: number) =>
    apiClient.delete<any>(`/boms/${bomId}`).then((r: any) => r.data),

  // Reparse BOM
  reparse: (bomId: number) =>
    apiClient.post<BOM>(`/boms/${bomId}/reparse`).then((r: any) => r.data),
};

export default apiClient;
