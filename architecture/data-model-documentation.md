# Design Plan: AIDE Data Model Documentation

## 1. Executive Summary & Goals
This document provides a comprehensive description of the AIDE (Advanced Intrusion Detection Environment) metastore's database schema. Its purpose is to serve as a single source of truth for developers and data engineers, ensuring a clear understanding of the data model.

The key goals are:

*   **Clarity and Understanding:** To explain the purpose of each table and column, fostering a shared understanding across teams.

*   **Detailed Explanations:** To provide in-depth examples for complex and non-obvious columns, reducing ambiguity and accelerating development.

*   **Consistency:** To establish a foundational document that can be versioned and updated as the data model evolves, ensuring accuracy over time.

## 2. Data Model Overview

The AIDE data model is a normalized relational schema designed to capture the metadata of a complex data ecosystem. It revolves around a few core concepts:

*   **Systems:** The physical or logical platforms where data resides (e.g., a PostgreSQL database, a Kafka cluster).

*   **Data Types:** The native data types supported by each specific system (e.g., `VARCHAR`, `BIGINT` for PostgreSQL).

*   **Datasets:** The logical data assets within a system (e.g., a specific table, a Kafka topic).

*   **Fields & Schemas:** The versioned structure and attributes (fields) that make up a dataset.

The model uses UUIDs for primary keys and enforces relationships through foreign keys. A polymorphic association on the `datasets` table allows different kinds of datasets (e.g., `rdbms`, `kafka`) to share common attributes while storing their specific metadata in separate tables.

### 2.1. Common Columns

Several tables share a set of common metadata columns inherited from `MetaDataMixin`. These are:

| Column | Data Type | Description |
|---|---|---|
| `id` | UUID | The primary key for the record, generated automatically. |
| `created_at` | DateTime | Timestamp indicating when the record was created. |
| `updated_at` | DateTime | Timestamp indicating the last time the record was updated. |
| `created_by` | UUID | The `id` of the user who created the record. Can be null. |
| `updated_by` | UUID | The `id` of the user who last updated the record. Can be null. |
| `note` | Text | An optional free-text field for comments or additional information. |

---

## 3. Detailed Table Descriptions

### 3.1. `users` Table

Stores user account information for authentication and authorization within the AIDE system.

| Column | Data Type | Description |
|---|---|---|
| `email` | String(255) | The user's unique email address, used for login. |
| `hashed_password` | String(255) | The user's password, stored as a secure bcrypt hash. |
| `full_name` | Text | The user's full name. |
| `is_active` | Boolean | A flag to activate or deactivate the user's account. |
| `is_superuser` | Boolean | A flag indicating if the user has administrative privileges. |

### 3.2. `system_kinds` Table

Represents broad categories of data systems. This table provides a high-level classification.

| Column | Data Type | Description |
|---|---|---|
| `code` | String(255) | A short, unique, machine-readable identifier (e.g., `RDBMS`, `MESSAGE_QUEUE`). |
| `name` | Text | A human-readable name for the kind (e.g., "Relational Database", "Message Queue"). |

### 3.3. `system_flavors` Table

Represents a specific technology or "flavor" within a `system_kind`.

| Column | Data Type | Description |
|---|---|---|
| `code` | String(255) | A short, unique, machine-readable identifier (e.g., `POSTGRESQL`, `KAFKA`). |
| `name` | Text | A human-readable name for the flavor (e.g., "PostgreSQL", "Apache Kafka"). |
| `vendor` | Text | The name of the vendor or organization behind the technology (e.g., "PostgreSQL Global Development Group"). |
| `versions` | ARRAY(String) | An optional list of supported or known versions (e.g., `["14", "15", "16"]`). |
| `kind_id` | UUID | A foreign key linking to the `system_kinds` table. |

### 3.4. `data_types` Table

Defines the native data types available for a specific `system_flavor`. This is a crucial table for enabling cross-system type mapping and validation.

| Column | Data Type | Description |
|---|---|---|
| `system_flavor_id` | UUID | A foreign key linking to the `system_flavors` table. |
| `code` | String(255) | The native type name as used in the source system (e.g., `VARCHAR`, `DECIMAL`). |
| `params_schema` | JSONB | **(Complex)** A JSON Schema object defining the parameters this type accepts. |
| `render_template` | Text | **(Complex)** A template string for generating the final type definition. |

#### Complex Column Explanations

*   `params_schema`: This column defines the "shape" of a data type. It's a JSON Schema that validates the parameters a type can have. For example, a `DECIMAL` type in a database needs `precision` and `scale`. The `params_schema` enforces this.

    **Example for a PostgreSQL `DECIMAL` type:**

    ```json
    {
      "type": "object",
      "properties": {
        "precision": {
          "type": "integer",
          "description": "Total number of digits."
        },
        "scale": {
          "type": "integer",
          "description": "Number of digits after the decimal point."
        }
      },
      "required": ["precision", "scale"]
    }
    ```

*   `render_template`: This is a Jinja2-style template that uses the parameters defined in `params_schema` to construct the final, syntactically correct data type string for the target system.

    **Example for a PostgreSQL `DECIMAL` type:**

    ```jinja
    DECIMAL({{ precision }}, {{ scale }})
    ```
    When combined with parameters `{"precision": 10, "scale": 2}`, this template renders to `DECIMAL(10, 2)`. For a type with no parameters like `INTEGER`, the template would simply be `INTEGER`.

### 3.5. `cast_rules` Table

Defines the rules for converting or "casting" from a source `data_type` to a target `data_type`.

| Column | Data Type | Description |
|---|---|---|
| `source_data_type_id` | UUID | Foreign key to `data_types` representing the original type. |
| `target_data_type_id` | UUID | Foreign key to `data_types` representing the destination type. |
| `param_mapping` | JSONB | **(Complex)** A JSON object describing how to map parameters from the source to the target. |
| `safety` | Enum | **(Complex)** An enum (`IMPLICIT`, `SAFE`, `UNSAFE`) indicating the safety of the cast. |

#### Complex Column Explanations

*   `safety`: This enum classifies the nature of the type conversion.

    *   `IMPLICIT`: The cast is always safe and can be done automatically without data loss (e.g., `INTEGER` to `BIGINT`).

    *   `SAFE`: The cast does not lose data, but it's not implicit and requires an explicit conversion function (e.g., `VARCHAR` to `INTEGER`, which can fail if the string is not a number).

    *   `UNSAFE`: The cast may result in loss of precision or data truncation (e.g., `BIGINT` to `INTEGER`, or `VARCHAR(50)` to `VARCHAR(20)`).

*   `param_mapping`: This JSON object provides a formula or mapping to calculate the parameters of the target data type based on the source's parameters. The keys are the target parameter names, and the values are expressions that can reference source parameters using `source.<param_name>`.

    **Example: Casting `ORACLE.NUMBER(p,s)` to `POSTGRES.DECIMAL(p,s)`**

    The source type (`ORACLE.NUMBER`) has parameters `p` (precision) and `s` (scale). The target type (`POSTGRES.DECIMAL`) also has `precision` and `scale`. The mapping is a direct one-to-one translation.

    ```json
    {
      "precision": "source.p",
      "scale": "source.s"
    }
    ```

    **Example: Casting `POSTGRES.VARCHAR(len)` to `SNOWFLAKE.VARCHAR(len)` but with a size increase**

    Imagine a rule that always adds 10 to the length when casting from PostgreSQL to Snowflake.

    ```json
    {
      "length": "source.len + 10"
    }
    ```

### 3.6. `datasets` and Child Tables

This is a set of tables using a "table-per-class" inheritance pattern to store metadata for different kinds of datasets. The base `datasets` table holds common information.

#### `datasets` (Base Table)

| Column | Data Type | Description |
|---|---|---|
| `system_id` | UUID | Foreign key to the `systems` table where this dataset resides. |
| `object_name` | Text | A unique identifier for the dataset within its system (e.g., a table name, a topic name). |
| `layer` | String(255) | The architectural layer of the dataset (e.g., `RAW`, `ODS`, `DWH`). |
| `is_active` | Boolean | A flag indicating if the dataset is currently in use. |
| `extra` | JSONB | A flexible field for storing any additional, non-standard metadata. |
| `kind` | String(255) | A discriminator column that specifies which child table holds the detailed metadata (e.g., `rdbms`, `kafka`). |

#### `dataset_rdbms`

Stores metadata specific to relational database tables or views.

| Column | Data Type | Description |
|---|---|---|
| `id` | UUID | Primary key, and a foreign key to `datasets.id`. |
| `catalog_name` | Text | The database/catalog name. |
| `schema_name` | Text | The schema name. |
| `table_name` | Text | The table or view name. |
| `is_view` | Boolean | Flag indicating if the object is a view. |
| `pk_columns` | ARRAY(String) | A list of column names that form the primary key. |
| `uq_constraints` | JSONB | A JSON object defining unique constraints. Example: `{"uq_email": ["email"]}`. |

#### `dataset_kafka`

Stores metadata specific to Apache Kafka topics.

| Column | Data Type | Description |
|---|---|---|
| `id` | UUID | Primary key, and a foreign key to `datasets.id`. |
| `topic` | Text | The full name of the Kafka topic. |
| `format` | String(255) | The message format used in the topic (e.g., `AVRO`, `JSON`, `PROTOBUF`). |
| `partitions` | Integer | The number of partitions for the topic. |
| `retention_ms` | BigInteger | The message retention period in milliseconds. |
| `key_columns` | ARRAY(String) | A list of field names from the message schema that constitute the message key. |

*(Similar detailed tables exist for `dataset_hive`, `dataset_storage`, and `dataset_sftp`)*

### 3.7. `fields` Table

Represents a logical field or attribute that can exist within a dataset. This allows a field to be defined once and reused across different versions of a dataset's schema.

| Column | Data Type | Description |
|---|---|---|
| `dataset_id` | UUID | Foreign key to the `datasets` table this field belongs to. |
| `name` | Text | The logical name of the field (e.g., `customer_email`). |
| `path` | Text | For nested data structures (like JSON), this represents the path to the field (e.g., `customer.address.zip_code`). |
| `pii_tags` | ARRAY(Text) | A list of tags indicating if the field contains Personally Identifiable Information (e.g., `["email", "pii"]`). |
| `extra` | JSONB | A flexible field for additional metadata about the field. |

### 3.8. `dataset_schemas` Table

Stores a specific, versioned schema for a dataset.

| Column | Data Type | Description |
|---|---|---|
| `dataset_id` | UUID | Foreign key to the `datasets` table. |
| `version_num` | Integer | The version number of the schema, which is unique per dataset. |
| `schema` | JSONB | A JSON object representing the full schema definition (e.g., an Avro schema JSON). |
| `extra` | JSONB | A flexible field for additional metadata about this schema version. |

### 3.9. `field_bindings` Table

This table acts as a bridge, connecting a logical `field` to a physical representation within a specific `dataset_schema`. It defines the field's position, data type, and nullability for that schema version.

| Column | Data Type | Description |
|---|---|---|
| `field_id` | UUID | Foreign key to the `fields` table. |
| `dataset_schema_id` | UUID | Foreign key to the `dataset_schemas` table. |
| `position` | Integer | The ordinal position of the field within the schema (e.g., column order). |
| `is_nullable` | Boolean | Flag indicating if the field can contain null values. |
| `data_type_id` | UUID | Foreign key to the `data_types` table, defining the physical type for this field. |
| `type_params` | JSONB | **(Complex)** A JSON object containing the specific parameter values for the data type. |

#### Complex Column Explanations

*   `type_params`: This column provides the concrete values for the parameters defined in the associated `data_types.params_schema`.

    **Example:**

    1.  A `field_binding` links to a `data_type` record with `code` = `VARCHAR` and `params_schema` = `{"properties": {"length": {"type": "integer"}}, "required": ["length"]}`.

    2.  To represent a `VARCHAR(255)`, the `type_params` column in the `field_bindings` table would contain:

        ```json
        {
          "length": 255
        }
        ```
    This allows the system to be both flexible in defining types and specific in instantiating them.

---

