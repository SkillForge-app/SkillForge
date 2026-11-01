import type { ApiClient } from "./client";
import type { paths } from "./schema";

type ProjectCreateInput =
  paths["/api/v1/projects"]["post"]["requestBody"]["content"]["application/json"];
type ProjectUpdateInput =
  paths["/api/v1/projects/{project_id}"]["patch"]["requestBody"]["content"]["application/json"];

export const projectsApi = (client: ApiClient) => ({
  list: () => client.GET("/api/v1/projects"),

  get: (projectId: string) =>
    client.GET("/api/v1/projects/{project_id}", {
      params: { path: { project_id: projectId } },
    }),

  create: (body: ProjectCreateInput) => client.POST("/api/v1/projects", { body }),

  update: (projectId: string, body: ProjectUpdateInput) =>
    client.PATCH("/api/v1/projects/{project_id}", {
      params: { path: { project_id: projectId } },
      body,
    }),

  delete: (projectId: string) =>
    client.DELETE("/api/v1/projects/{project_id}", {
      params: { path: { project_id: projectId } },
    }),
});
