"use client";

import { useId } from "react";

/** The subset is intentionally generic; fields come from AI-01's schema, not a local SkillSpec model. */
export type JsonSchema = {
  title?: string;
  description?: string;
  type?: "object" | "string" | "number" | "integer" | "boolean" | "array";
  format?: string;
  enum?: Array<string | number | boolean>;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
};

export type SchemaValidationError = {
  path: string;
  message: string;
  severity: "error" | "warning";
};

type SchemaDrivenFormProps = {
  schema: JsonSchema;
  value: Record<string, unknown>;
  errors?: SchemaValidationError[];
  onChange: (value: Record<string, unknown>) => void;
};

export function SchemaDrivenForm({ schema, value, errors = [], onChange }: SchemaDrivenFormProps) {
  const formId = useId();
  const properties = schema.properties ?? {};

  function update(path: string[], nextValue: unknown) {
    const next = structuredClone(value);
    let cursor: Record<string, unknown> = next;
    for (const key of path.slice(0, -1)) {
      const child = cursor[key];
      if (!child || typeof child !== "object" || Array.isArray(child)) cursor[key] = {};
      cursor = cursor[key] as Record<string, unknown>;
    }
    cursor[path[path.length - 1]] = nextValue;
    onChange(next);
  }

  return (
    <div className="schema-driven-form">
      {schema.description && <p className="schema-form-description">{schema.description}</p>}
      {Object.entries(properties).map(([key, fieldSchema]) => (
        <SchemaField
          key={`${formId}-${key}`}
          name={key}
          schema={fieldSchema}
          required={schema.required?.includes(key) ?? false}
          path={[key]}
          value={value[key]}
          errors={errors.filter(
            (error) =>
              error.path === key ||
              error.path.startsWith(`${key}.`) ||
              error.path.startsWith(`${key}[`),
          )}
          onChange={update}
        />
      ))}
    </div>
  );
}

type SchemaFieldProps = {
  name: string;
  schema: JsonSchema;
  required: boolean;
  path: string[];
  value: unknown;
  errors: SchemaValidationError[];
  onChange: (path: string[], value: unknown) => void;
};

function SchemaField({ name, schema, required, path, value, errors, onChange }: SchemaFieldProps) {
  const inputId = useId();
  const errorId = `${inputId}-errors`;
  const label = schema.title ?? name;
  const invalid = errors.some((error) => error.severity === "error");

  if (schema.type === "object" || schema.properties) {
    const objectValue =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
    return (
      <fieldset className="schema-form-object">
        <legend>
          {label}
          {required && <span aria-hidden="true"> *</span>}
        </legend>
        {schema.description && <p className="schema-form-hint">{schema.description}</p>}
        <SchemaDrivenForm
          schema={schema}
          value={objectValue}
          errors={errors.map((error) => ({ ...error, path: error.path.slice(name.length + 1) }))}
          onChange={(next) => onChange(path, next)}
        />
      </fieldset>
    );
  }

  return (
    <div className="schema-form-field">
      <label htmlFor={inputId}>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </label>
      {schema.description && <p className="schema-form-hint">{schema.description}</p>}
      {schema.type === "boolean" ? (
        <input
          id={inputId}
          type="checkbox"
          checked={value === true}
          aria-invalid={invalid}
          aria-describedby={errors.length ? errorId : undefined}
          onChange={(event) => onChange(path, event.target.checked)}
        />
      ) : schema.enum ? (
        <select
          id={inputId}
          value={value === undefined ? "" : String(value)}
          aria-invalid={invalid}
          aria-describedby={errors.length ? errorId : undefined}
          onChange={(event) => {
            const selected = schema.enum?.find((option) => String(option) === event.target.value);
            onChange(path, selected);
          }}
        >
          <option value="">اختر قيمة</option>
          {schema.enum.map((option) => (
            <option value={String(option)} key={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : schema.type === "array" && schema.items?.enum ? (
        <div className="schema-form-enum-list" role="group" aria-label={label}>
          {schema.items.enum.map((option) => {
            const selectedValues = Array.isArray(value) ? value : [];
            const checked = selectedValues.some((item) => String(item) === String(option));
            return (
              <label className="schema-form-enum-option" key={String(option)}>
                <input
                  type="checkbox"
                  checked={checked}
                  aria-invalid={invalid}
                  aria-describedby={errors.length ? errorId : undefined}
                  onChange={() =>
                    onChange(
                      path,
                      checked
                        ? selectedValues.filter((item) => String(item) !== String(option))
                        : [...selectedValues, option],
                    )
                  }
                />
                <span>{String(option)}</span>
              </label>
            );
          })}
        </div>
      ) : schema.type === "array" ? (
        <textarea
          id={inputId}
          value={Array.isArray(value) ? value.map(String).join("\n") : ""}
          aria-invalid={invalid}
          aria-describedby={errors.length ? errorId : undefined}
          placeholder="اكتب كل قيمة في سطر"
          rows={3}
          onChange={(event) => onChange(path, event.target.value.split("\n").filter(Boolean))}
        />
      ) : schema.type === "string" && !schema.enum ? (
        <textarea
          id={inputId}
          value={typeof value === "string" ? value : ""}
          minLength={schema.minLength}
          maxLength={schema.maxLength}
          aria-invalid={invalid}
          aria-describedby={errors.length ? errorId : undefined}
          rows={schema.format === "textarea" || (schema.maxLength ?? 0) > 160 ? 4 : 2}
          onChange={(event) => onChange(path, event.target.value)}
        />
      ) : (
        <input
          id={inputId}
          type={schema.type === "number" || schema.type === "integer" ? "number" : "text"}
          value={value === undefined || value === null ? "" : String(value)}
          min={schema.minimum}
          max={schema.maximum}
          step={schema.type === "integer" ? 1 : "any"}
          aria-invalid={invalid}
          aria-describedby={errors.length ? errorId : undefined}
          onChange={(event) => {
            const next = event.target.value;
            onChange(
              path,
              schema.type === "number" || schema.type === "integer"
                ? next === ""
                  ? undefined
                  : Number(next)
                : next,
            );
          }}
        />
      )}
      {errors.length > 0 && (
        <ul className="schema-form-errors" id={errorId}>
          {errors.map((error, index) => (
            <li
              className={`schema-form-error schema-form-error-${error.severity}`}
              key={`${error.path}-${index}`}
            >
              {error.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
