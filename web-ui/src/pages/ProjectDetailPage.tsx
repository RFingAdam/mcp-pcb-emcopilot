import React, { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { projectsApi, schematicsApi, bomApi, PCBLayout, Schematic, BOM } from '../api/client';

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [layoutName, setLayoutName] = useState('');
  const [schematicFile, setSchematicFile] = useState<File | null>(null);
  const [bomFile, setBomFile] = useState<File | null>(null);

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => projectsApi.get(Number(projectId)),
  });

  const { data: layouts } = useQuery({
    queryKey: ['layouts', projectId],
    queryFn: () => projectsApi.listLayouts(Number(projectId)),
  });

  const { data: schematics } = useQuery({
    queryKey: ['schematics', projectId],
    queryFn: () => schematicsApi.list(Number(projectId)),
  });

  const { data: boms } = useQuery({
    queryKey: ['boms', projectId],
    queryFn: () => bomApi.list(Number(projectId)),
  });

  const uploadMutation = useMutation({
    mutationFn: ({ file, name }: { file: File; name?: string }) =>
      projectsApi.uploadLayout(Number(projectId), file, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['layouts', projectId] });
      setUploadFile(null);
      setLayoutName('');
    },
  });

  const schematicUploadMutation = useMutation({
    mutationFn: (file: File) => schematicsApi.upload(Number(projectId), file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schematics', projectId] });
      setSchematicFile(null);
    },
  });

  const bomUploadMutation = useMutation({
    mutationFn: (file: File) => bomApi.upload(Number(projectId), file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boms', projectId] });
      setBomFile(null);
    },
  });

  // Delete mutations
  const deleteProjectMutation = useMutation({
    mutationFn: () => projectsApi.delete(Number(projectId)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate('/');
    },
  });

  const deleteLayoutMutation = useMutation({
    mutationFn: (layoutId: number) => projectsApi.deleteLayout(Number(projectId), layoutId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['layouts', projectId] });
    },
  });

  const deleteSchematicMutation = useMutation({
    mutationFn: (schematicId: number) => schematicsApi.delete(schematicId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schematics', projectId] });
    },
  });

  const deleteBomMutation = useMutation({
    mutationFn: (bomId: number) => bomApi.delete(bomId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boms', projectId] });
    },
  });

  const handleUpload = (e: React.FormEvent) => {
    e.preventDefault();
    if (uploadFile) {
      uploadMutation.mutate({ file: uploadFile, name: layoutName || undefined });
    }
  };

  const handleSchematicUpload = (e: React.FormEvent) => {
    e.preventDefault();
    if (schematicFile) {
      schematicUploadMutation.mutate(schematicFile);
    }
  };

  const handleBomUpload = (e: React.FormEvent) => {
    e.preventDefault();
    if (bomFile) {
      bomUploadMutation.mutate(bomFile);
    }
  };

  const handleDeleteProject = () => {
    if (window.confirm(`Are you sure you want to delete "${project?.name}"? This will also delete all layouts, schematics, and BOMs.`)) {
      deleteProjectMutation.mutate();
    }
  };

  const handleDeleteLayout = (layoutId: number, layoutName: string) => {
    if (window.confirm(`Delete layout "${layoutName}"?`)) {
      deleteLayoutMutation.mutate(layoutId);
    }
  };

  const handleDeleteSchematic = (schematicId: number, filename: string) => {
    if (window.confirm(`Delete schematic "${filename}"?`)) {
      deleteSchematicMutation.mutate(schematicId);
    }
  };

  const handleDeleteBom = (bomId: number, filename: string) => {
    if (window.confirm(`Delete BOM "${filename}"?`)) {
      deleteBomMutation.mutate(bomId);
    }
  };

  if (!project) return <div className="loading">Loading project...</div>;

  return (
    <div>
      <div className="mb-3">
        <Link to="/" className="btn btn-secondary">← Back to Projects</Link>
      </div>

      <div className="card mb-3">
        <div className="flex-between">
          <h1>{project.name}</h1>
          <button
            className="btn btn-danger btn-sm"
            onClick={handleDeleteProject}
            disabled={deleteProjectMutation.isPending}
          >
            {deleteProjectMutation.isPending ? 'Deleting...' : 'Delete Project'}
          </button>
        </div>
        {project.description && <p className="text-muted mt-1">{project.description}</p>}
        <p className="text-small text-muted mt-2">
          Created: {new Date(project.created_at).toLocaleDateString()}
        </p>
      </div>

      <div className="card mb-3">
        <h2>Upload Design Files</h2>

        {/* PCB Layout Upload */}
        <div className="mb-3" style={{ borderBottom: '1px solid #e0e0e0', paddingBottom: '1rem' }}>
          <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>PCB Layout</h3>
          <form onSubmit={handleUpload}>
            <div className="form-group">
              <label>Layout File (Altium, Gerber, ODB++, JSON, or Image)</label>
              <input
                type="file"
                className="form-control"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                accept=".PcbDoc,.pcbdoc,.gbr,.grb,.ger,.tgz,.tar.gz,.tar,.zip,.json,.png,.jpg,.jpeg"
              />
            </div>
            <div className="form-group">
              <label>Layout Name (optional)</label>
              <input
                type="text"
                className="form-control"
                value={layoutName}
                onChange={(e) => setLayoutName(e.target.value)}
                placeholder="e.g., Top Layer, Rev A"
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!uploadFile || uploadMutation.isPending}
            >
              {uploadMutation.isPending ? 'Uploading...' : 'Upload Layout'}
            </button>
          </form>
        </div>

        {/* Schematic Upload */}
        <div className="mb-3" style={{ borderBottom: '1px solid #e0e0e0', paddingBottom: '1rem' }}>
          <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Schematic</h3>
          <form onSubmit={handleSchematicUpload}>
            <div className="form-group">
              <label>Schematic File (KiCad .kicad_sch)</label>
              <input
                type="file"
                className="form-control"
                onChange={(e) => setSchematicFile(e.target.files?.[0] || null)}
                accept=".kicad_sch,.sch,.schdoc"
              />
              <small className="text-muted">Supports KiCad (.kicad_sch) and Altium (.SchDoc) schematics.</small>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!schematicFile || schematicUploadMutation.isPending}
            >
              {schematicUploadMutation.isPending ? 'Uploading...' : 'Upload Schematic'}
            </button>
          </form>
          {schematics && schematics.length > 0 && (
            <div className="mt-2">
              <strong>Uploaded Schematics:</strong>
              <ul className="mt-1" style={{ marginBottom: 0 }}>
                {schematics.map((sch: Schematic) => (
                  <li key={sch.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>{sch.filename}</span>
                    <span className={`badge badge-${sch.is_parsed ? 'success' : 'warning'}`}>
                      {sch.is_parsed ? 'Parsed' : 'Pending'}
                    </span>
                    {sch.sheet_count && <span className="text-muted">({sch.sheet_count} sheets)</span>}
                    <button
                      className="btn btn-danger btn-xs"
                      onClick={() => handleDeleteSchematic(sch.id, sch.filename)}
                      style={{ marginLeft: 'auto', padding: '0.1rem 0.4rem', fontSize: '0.75rem' }}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* BOM Upload */}
        <div>
          <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Bill of Materials (BOM)</h3>
          <form onSubmit={handleBomUpload}>
            <div className="form-group">
              <label>BOM File (CSV or Excel)</label>
              <input
                type="file"
                className="form-control"
                onChange={(e) => setBomFile(e.target.files?.[0] || null)}
                accept=".csv,.xlsx,.xls"
              />
              <small className="text-muted">Flexible column mapping: Reference, Quantity, Part Number, Value, etc.</small>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!bomFile || bomUploadMutation.isPending}
            >
              {bomUploadMutation.isPending ? 'Uploading...' : 'Upload BOM'}
            </button>
          </form>
          {boms && boms.length > 0 && (
            <div className="mt-2">
              <strong>Uploaded BOMs:</strong>
              <ul className="mt-1" style={{ marginBottom: 0 }}>
                {boms.map((bom: BOM) => (
                  <li key={bom.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>{bom.filename}</span>
                    <span className={`badge badge-${bom.is_parsed ? 'success' : 'warning'}`}>
                      {bom.is_parsed ? 'Parsed' : 'Pending'}
                    </span>
                    {bom.total_items && <span className="text-muted">({bom.total_items} items)</span>}
                    <button
                      className="btn btn-danger btn-xs"
                      onClick={() => handleDeleteBom(bom.id, bom.filename)}
                      style={{ marginLeft: 'auto', padding: '0.1rem 0.4rem', fontSize: '0.75rem' }}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="flex-between mb-2">
          <h2>PCB Layouts</h2>
          {layouts && layouts.length > 0 && (
            <Link
              to={`/projects/${projectId}/ai-review`}
              className="btn btn-success"
            >
              AI Review
            </Link>
          )}
        </div>

        {!layouts || layouts.length === 0 ? (
          <p className="text-muted">No layouts uploaded yet.</p>
        ) : (
          <div className="grid grid-3">
              {layouts.map((layout: PCBLayout) => (
                <div key={layout.id} className="card">
                  <h3>{layout.layout_name}</h3>
                  <p className="text-small text-muted">
                  Type: {layout.file_type || 'unknown'}<br />
                  Size: {layout.file_size_bytes ? `${(layout.file_size_bytes / 1024).toFixed(1)} KB` : 'N/A'}<br />
                  Version: {layout.version}<br />
                  Layers: {layout.layer_count ?? '—'}<br />
                  Dimensions: {layout.board_width_mm && layout.board_height_mm
                    ? `${layout.board_width_mm?.toFixed(1)} x ${layout.board_height_mm?.toFixed(1)} mm`
                    : '—'}
                  </p>
                  <div className="flex gap-1 mt-1">
                    <span className={`badge badge-${
                      layout.is_parsed ? 'success' : layout.parse_error ? 'error' : 'warning'
                    }`}>
                      {layout.is_parsed ? 'Parsed' : layout.parse_error ? 'Parse Error' : 'Parsing'}
                    </span>
                    {layout.parse_error && (
                      <span className="text-small text-warning">{layout.parse_error}</span>
                    )}
                  </div>
                  <div className="flex gap-1 mt-2">
                    <Link
                      to={`/projects/${projectId}/simulations/new?layoutId=${layout.id}`}
                      className="btn btn-primary btn-sm"
                    >
                      Configure Simulation
                    </Link>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDeleteLayout(layout.id, layout.layout_name)}
                    >
                      Delete
                    </button>
                  </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
