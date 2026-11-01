import type { ApiClient } from "./client";
import type { paths } from "./schema";

type RepositoryCreateInput =
  paths["/api/v1/projects/{project_id}/repositories"]["post"]["requestBody"]["content"]["application/json"];
type RepositoryUpdateInput =
  paths["/api/v1/repositories/{repository_id}"]["patch"]["requestBody"]["content"]["application/json"];

export const repositoriesApi = (client: ApiClient) => ({
  list: (projectId: string) =>
    client.GET("/api/v1/projects/{project_id}/repositories", {
      params: { path: { project_id: projectId } },
    }),

  get: (repositoryId: string) =>
    client.GET("/api/v1/repositories/{repository_id}", {
      params: { path: { repository_id: repositoryId } },
    }),

  create: (projectId: string, body: RepositoryCreateInput) =>
    client.POST("/api/v1/projects/{project_id}/repositories", {
      params: { path: { project_id: projectId } },
      body,
    }),

  update: (repositoryId: string, body: RepositoryUpdateInput) =>
    client.PATCH("/api/v1/repositories/{repository_id}", {
      params: { path: { repository_id: repositoryId } },
      body,
    }),

  delete: (repositoryId: string) =>
    client.DELETE("/api/v1/repositories/{repository_id}", {
      params: { path: { repository_id: repositoryId } },
    }),
});
