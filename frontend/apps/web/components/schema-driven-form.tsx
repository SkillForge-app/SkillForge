"use client";

import { useId } from "react";

/** JSON Schema subset used by the AI-01 SkillSpec contract. */
export type JsonSchema = {
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  title?: string;
  description?: string;
  type?: "object" | "string" | "number" | "integer" | "boolean" | "array" | "null";
  format?: string;
  const?: string | number | boolean | null;
  default?: unknown;
  enum?: Array<string | number | boolean>;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  uniqueItems?: boolean;
};

export type SchemaValidationIssue = {
  path: string;
  code: string;
  message: string;
  severity: "error" | "warning";
};

type SchemaDrivenFormProps = {
  schema: JsonSchema;
  value: Record<string, unknown>;
  issues?: SchemaValidationIssue[];
  onChange: (value: Record<string, unknown>) => void;
};

export function createInitialValue(schema: JsonSchema): Record<string, unknown> {
  return createValue(resolveSchema(schema, schema), schema) as Record<string, unknown>;
}

export function SchemaDrivenForm({ schema, value, issues = [], onChange }: SchemaDrivenFormProps) {
  const formId = useId();

  function update(path: string, nextValue: unknown) {
    const next = structuredClone(value);
    const parts = parsePointer(path);
    if (parts.length === 0) return;
    let cursor: Record<string, unknown> | unknown[] = next;
    for (let index = 0; index < parts.length - 1; index += 1) {
      const part = parts[index];
      const key: string | number = Array.isArray(cursor) ? Number(part) : part;
      let child: unknown = cursor[key as never];
      if (!child || typeof child !== "object") {
        child = /^\d+$/.test(parts[index + 1]) ? [] : {};
        cursor[key as never] = child as never;
      }
      cursor = child as Record<string, unknown> | unknown[];
    }
    const last = parts[parts.length - 1];
    const key: string | number = Array.isArray(cursor) ? Number(last) : last;
    cursor[key as never] = nextValue as never;
    onChange(next);
  }

  return (
    <div className="schema-driven-form" id={formId}>
      {schema.description && <p className="schema-form-description">{schema.description}</p>}
      <SchemaNode
        rootSchema={schema}
        schema={schema}
        value={value}
        path=""
        issues={issues}
        onChange={update}
      />
    </div>
  );
}

type SchemaNodeProps = {
  rootSchema: JsonSchema;
  schema: JsonSchema;
  value: unknown;
  path: string;
  issues: SchemaValidationIssue[];
  onChange: (path: string, value: unknown) => void;
  label?: string;
  required?: boolean;
};

function SchemaNode({
  rootSchema,
  schema: sourceSchema,
  value,
  path,
  issues,
  onChange,
  label,
  required = false,
}: SchemaNodeProps) {
  const id = useId();
  const schema = resolveSchema(sourceSchema, rootSchema);
  const title = label ?? schema.title ?? pointerLabel(path);
  const fieldIssues = issues.filter((issue) => issue.path === path);
  const childIssues = issues.filter(
    (issue) => issue.path.startsWith(`${path}/`) && issue.path !== path,
  );
  const invalid = fieldIssues.some((issue) => issue.severity === "error");
  const helpId = `${id}-help`;
  const issuesId = `${id}-issues`;

  if (schema.const !== undefined) {
    return (
      <div className="schema-form-field">
        <span className="schema-form-label">{title}</span>
        {schema.description && (
          <p className="schema-form-hint" id={helpId}>
            {schema.description}
          </p>
        )}
        <output
          className="schema-form-constant"
          aria-describedby={schema.description ? helpId : undefined}
        >
          {String(schema.const)}
        </output>
        <IssueList issues={fieldIssues} id={issuesId} />
      </div>
    );
  }

  if (schema.type === "object" || schema.properties) {
    const objectValue = isRecord(value) ? value : {};
    return (
      <fieldset className={`schema-form-object ${path === "" ? "schema-form-root" : ""}`}>
        {path !== "" && (
          <legend>
            {title}
            {required && <span aria-hidden="true"> *</span>}
          </legend>
        )}
        {schema.description && <p className="schema-form-hint">{schema.description}</p>}
        <div className="schema-form-object-fields">
          {Object.entries(schema.properties ?? {}).map(([key, childSchema]) => {
            const childPath = joinPointer(path, key);
            return (
              <SchemaNode
                key={childPath}
                rootSchema={rootSchema}
                schema={childSchema}
                value={objectValue[key]}
                path={childPath}
                issues={childIssues}
                onChange={onChange}
                required={schema.required?.includes(key)}
              />
            );
          })}
        </div>
        <IssueList issues={fieldIssues} id={issuesId} />
      </fieldset>
    );
  }

  if (schema.type === "array" && schema.items?.enum) {
    const selected = Array.isArray(value) ? value : [];
    return (
      <section className="schema-form-array" aria-labelledby={`${id}-label`}>
        <div className="schema-form-array-heading">
          <div>
            <h3 id={`${id}-label`}>
              {title}
              {required && <span aria-hidden="true"> *</span>}
            </h3>
            {schema.description && <p className="schema-form-hint">{schema.description}</p>}
          </div>
        </div>
        <div className="schema-form-enum-list" role="group" aria-labelledby={`${id}-label`}>
          {schema.items.enum.map((option) => {
            const checked = selected.some((item) => String(item) === String(option));
            const canAdd = schema.maxItems === undefined || selected.length < schema.maxItems;
            return (
              <label className="schema-form-enum-option" key={String(option)}>
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!checked && !canAdd}
                  onChange={() =>
                    onChange(
                      path,
                      checked
                        ? selected.filter((item) => String(item) !== String(option))
                        : [...selected, option],
                    )
                  }
                />
                <span>{String(option)}</span>
              </label>
            );
          })}
        </div>
        <IssueList issues={fieldIssues} id={issuesId} />
      </section>
    );
  }

  if (schema.type === "array") {
    const items = Array.isArray(value) ? value : [];
    const itemSchema = schema.items ?? { type: "string" as const };
    const atMax = schema.maxItems !== undefined && items.length >= schema.maxItems;
    const atMin = schema.minItems !== undefined && items.length <= schema.minItems;
    return (
      <section className="schema-form-array" aria-labelledby={`${id}-label`}>
        <div className="schema-form-array-heading">
          <div>
            <h3 id={`${id}-label`}>
              {title}
              {required && <span aria-hidden="true"> *</span>}
            </h3>
            {schema.description && <p className="schema-form-hint">{schema.description}</p>}
          </div>
          <span className="schema-form-count">
            {items.length}
            {schema.maxItems !== undefined ? ` / ${schema.maxItems}` : ""}
          </span>
        </div>
        {items.length ? (
          <div className="schema-form-array-items">
            {items.map((item, index) => {
              const itemPath = joinPointer(path, String(index));
              return (
                <div className="schema-form-array-item" key={itemPath}>
                  <SchemaNode
                    rootSchema={rootSchema}
                    schema={itemSchema}
                    value={item}
                    path={itemPath}
                    label={schema.title ? `${schema.title} ${index + 1}` : `عنصر ${index + 1}`}
                    issues={childIssues}
                    onChange={onChange}
                  />
                  <button
                    className="schema-form-remove"
                    type="button"
                    disabled={atMin}
                    onClick={() =>
                      onChange(
                        path,
                        items.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                    aria-label={`حذف ${title} ${index + 1}`}
                  >
                    حذف
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="schema-form-empty">مفيش عناصر مضافة.</p>
        )}
        <button
          className="schema-form-add"
          type="button"
          disabled={atMax}
          onClick={() => onChange(path, [...items, createValue(itemSchema, rootSchema)])}
        >
          + إضافة عنصر
        </button>
        <IssueList issues={fieldIssues} id={issuesId} />
      </section>
    );
  }

  const describedBy =
    [schema.description ? helpId : "", fieldIssues.length ? issuesId : ""]
      .filter(Boolean)
      .join(" ") || undefined;
  const shared = { id, required, "aria-invalid": invalid, "aria-describedby": describedBy };
  return (
    <div className="schema-form-field">
      <label htmlFor={id}>
        {title}
        {required && <span aria-hidden="true"> *</span>}
      </label>
      {schema.description && (
        <p className="schema-form-hint" id={helpId}>
          {schema.description}
        </p>
      )}
      {schema.enum ? (
        <select
          {...shared}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) =>
            onChange(
              path,
              schema.enum?.find((option) => String(option) === event.target.value),
            )
          }
        >
          <option value="">اختر قيمة</option>
          {schema.enum.map((option) => (
            <option value={String(option)} key={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : schema.type === "boolean" ? (
        <input
          {...shared}
          className="schema-form-checkbox"
          type="checkbox"
          checked={value === true}
          onChange={(event) => onChange(path, event.target.checked)}
        />
      ) : schema.type === "string" && shouldUseTextarea(schema) ? (
        <textarea
          {...shared}
          value={typeof value === "string" ? value : ""}
          minLength={schema.minLength}
          maxLength={schema.maxLength}
          rows={4}
          onChange={(event) => onChange(path, event.target.value)}
        />
      ) : (
        <input
          {...shared}
          type={inputType(schema)}
          value={value === undefined || value === null ? "" : String(value)}
          min={schema.minimum}
          max={schema.maximum}
          minLength={schema.minLength}
          maxLength={schema.maxLength}
          pattern={schema.pattern}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(
              path,
              schema.type === "number" || schema.type === "integer"
                ? raw === ""
                  ? undefined
                  : Number(raw)
                : raw,
            );
          }}
        />
      )}
      <IssueList issues={fieldIssues} id={issuesId} />
    </div>
  );
}

function IssueList({ issues, id }: { issues: SchemaValidationIssue[]; id: string }) {
  if (!issues.length) return null;
  return (
    <ul className="schema-form-issues" id={id}>
      {issues.map((issue, index) => (
        <li
          className={`schema-form-issue schema-form-issue-${issue.severity}`}
          key={`${issue.code}-${index}`}
        >
          <span>{issue.message}</span>
          <code dir="ltr">{issue.code}</code>
        </li>
      ))}
    </ul>
  );
}

function resolveSchema(schema: JsonSchema, root: JsonSchema): JsonSchema {
  let current = schema;
  const seen = new Set<string>();
  while (current.$ref && !seen.has(current.$ref)) {
    seen.add(current.$ref);
    const target = resolvePointer(root, current.$ref);
    if (!target) break;
    const siblings = { ...current };
    delete siblings.$ref;
    current = { ...target, ...siblings };
  }
  if (current.anyOf?.length) {
    const variant = current.anyOf.find((option) => option.type !== "null") ?? current.anyOf[0];
    const siblings = { ...current };
    delete siblings.anyOf;
    current = { ...variant, ...siblings };
  }
  return current;
}

function resolvePointer(root: JsonSchema, pointer: string): JsonSchema | undefined {
  if (!pointer.startsWith("#/")) return undefined;
  let current: unknown = root;
  for (const segment of parsePointer(pointer.slice(1))) {
    if (!isRecord(current)) return undefined;
    current = current[segment];
  }
  return isRecord(current) ? (current as JsonSchema) : undefined;
}

function createValue(schema: JsonSchema, root: JsonSchema): unknown {
  const resolved = resolveSchema(schema, root);
  if (resolved.const !== undefined) return resolved.const;
  if (resolved.default !== undefined && resolved.default !== null)
    return structuredClone(resolved.default);
  if (resolved.type === "object" || resolved.properties) {
    const value: Record<string, unknown> = {};
    for (const key of resolved.required ?? []) {
      const child = resolved.properties?.[key];
      if (child) value[key] = createValue(child, root);
    }
    return value;
  }
  if (resolved.type === "array") return [];
  if (resolved.type === "string") return "";
  if (resolved.type === "boolean") return false;
  return undefined;
}

function parsePointer(pointer: string): string[] {
  if (!pointer || pointer === "#") return [];
  const path = pointer.startsWith("#") ? pointer.slice(1) : pointer;
  return path
    .split("/")
    .slice(1)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function joinPointer(base: string, segment: string): string {
  return `${base}/${segment.replace(/~/g, "~0").replace(/\//g, "~1")}`;
}

function pointerLabel(path: string): string {
  const parts = parsePointer(path);
  return parts.length ? parts[parts.length - 1].replaceAll("_", " ") : "SkillSpec";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function shouldUseTextarea(schema: JsonSchema): boolean {
  return schema.format === "textarea" || (schema.maxLength ?? 0) > 160;
}

function inputType(schema: JsonSchema): string {
  if (schema.format === "date") return "date";
  if (schema.format === "uri") return "url";
  if (schema.type === "number" || schema.type === "integer") return "number";
  return "text";
}
