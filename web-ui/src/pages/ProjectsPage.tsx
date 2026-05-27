import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { projectsApi, Project } from '../api/client';

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');

  const { data: projects, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  });

  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setShowCreateForm(false);
      setNewProjectName('');
      setNewProjectDesc('');
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (newProjectName.trim()) {
      createMutation.mutate({
        name: newProjectName,
        description: newProjectDesc || undefined,
      });
    }
  };

  if (isLoading) return <div className="loading">Loading projects...</div>;
  if (error) return <div className="error">Error loading projects</div>;

  return (
    <div>
      <div className="flex-between mb-3">
        <h1>Design Projects</h1>
        <button
          className="btn btn-primary"
          onClick={() => setShowCreateForm(!showCreateForm)}
        >
          {showCreateForm ? 'Cancel' : 'New Project'}
        </button>
      </div>

      {showCreateForm && (
        <div className="card mb-3">
          <h2>Create New Project</h2>
          <form onSubmit={handleCreate}>
            <div className="form-group">
              <label>Project Name *</label>
              <input
                type="text"
                className="form-control"
                value={newProjectName}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewProjectName(e.target.value)}
                placeholder="Enter project name"
                required
              />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea
                className="form-control"
                value={newProjectDesc}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setNewProjectDesc(e.target.value)}
                placeholder="Optional description"
                rows={3}
              />
            </div>
            <button type="submit" className="btn btn-primary mr-2">
              Create Project
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowCreateForm(false)}
            >
              Cancel
            </button>
          </form>
        </div>
      )}

      {!projects || projects.length === 0 ? (
        <div className="card">
          <p className="text-muted">No projects yet. Create your first project to get started!</p>
        </div>
      ) : (
        <div className="grid grid-2">
          {projects.map((project: Project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link to={`/projects/${project.id}`} className="card" style={{ textDecoration: 'none', color: 'inherit' }}>
      <h3>{project.name}</h3>
      {project.description && (
        <p className="text-muted text-small mt-1">{project.description}</p>
      )}
      <p className="text-muted text-small mt-2">
        Created: {new Date(project.created_at).toLocaleDateString()}
      </p>
    </Link>
  );
}
