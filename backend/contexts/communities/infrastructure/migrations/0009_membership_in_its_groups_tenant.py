"""Review of the membership module (docs/architecture/review-membership-module.md, B1).

A membership belongs to its group's tenant. Row-level security keeps a
membership inside the current tenant, but a declared cross-tenant operation
sees every group, so nothing stopped it writing a membership into tenant A for
a group of tenant B. The allocation trigger already reads the group row; it
now also refuses a membership whose tenant is not the group's. It runs before
the tenant stamp (triggers fire by name), so it compares the tenant the row
will get: the one given, else the current tenant.
"""
from django.db import migrations

ALLOCATE = """
CREATE OR REPLACE FUNCTION communities_membership_allocate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    seq integer;
    group_tenant bigint;
BEGIN
    UPDATE communities_group SET last_member_sequence = last_member_sequence + 1
        WHERE id = NEW.group_id RETURNING last_member_sequence, tenant_id INTO seq, group_tenant;
    IF seq IS NULL THEN
        RAISE EXCEPTION 'membership for an unknown group' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF coalesce(NEW.tenant_id, wepl_current_tenant()) IS DISTINCT FROM group_tenant THEN
        RAISE EXCEPTION 'a membership belongs to its group''s tenant (%)', group_tenant
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.member_code IS DISTINCT FROM 'M' || lpad(seq::text, greatest(2, length(seq::text)), '0') THEN
        RAISE EXCEPTION 'member code % is not the next in this group (M%)', NEW.member_code, seq
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
"""

PREVIOUS = """
CREATE OR REPLACE FUNCTION communities_membership_allocate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    seq integer;
BEGIN
    UPDATE communities_group SET last_member_sequence = last_member_sequence + 1
        WHERE id = NEW.group_id RETURNING last_member_sequence INTO seq;
    IF seq IS NULL THEN
        RAISE EXCEPTION 'membership for an unknown group' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.member_code IS DISTINCT FROM 'M' || lpad(seq::text, greatest(2, length(seq::text)), '0') THEN
        RAISE EXCEPTION 'member code % is not the next in this group (M%)', NEW.member_code, seq
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0008_tenant_is_a_group")]
    operations = [migrations.RunSQL(ALLOCATE, PREVIOUS)]
