"""Initial schema + non-geographic seeds.

Revision ID: 0001
Revises:
Create Date: 2026-10-22

The whole schema in one step (docs/04). Seeds only what every instance needs
regardless of geography: the single `buyer_profile` row and the default
`alert_rules` setting (docs/09 §2). Property-tax rates come from the geography
file (docs/06 §8), not from here. Both inserts are guarded so re-running is a
no-op.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Defaults per docs/09-alerts-spec.md §2.
ALERT_RULES = {
    "price_cut": {"enabled": True, "price_band_pct": 0.20},
    "relist": {"enabled": True},
    "back_on_market": {"enabled": True},
    "new_listing_match": {"enabled": True, "min_beds": 3},
    "new_comp_sold": {"enabled": True, "radius_mi": 0.5},
    "offer_date_soon": {"enabled": True, "days_buckets": [3, 1]},
    "rate_move": {"enabled": True, "bps_threshold": 25},
    "scan_failure": {"enabled": True, "consecutive_days": 2},
    "watched_status": {"enabled": True},
}


def upgrade() -> None:
    op.create_table('buyer_profile',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('cash_available', sa.Integer(), nullable=False),
    sa.Column('down_payment', sa.Integer(), nullable=False),
    sa.Column('rate_assumption', sa.Float(), nullable=True),
    sa.Column('appraisal_gap_tolerance_pct', sa.Float(), nullable=False),
    sa.Column('insurance_monthly_est', sa.Integer(), nullable=False),
    sa.Column('include_earthquake_ins', sa.Boolean(), nullable=False),
    sa.Column('target_zips', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('market_metrics',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('geo_type', sa.Text(), nullable=False),
    sa.Column('geo_id', sa.Text(), nullable=False),
    sa.Column('period_start', sa.Text(), nullable=False),
    sa.Column('period', sa.Text(), nullable=False),
    sa.Column('metric', sa.Text(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('geo_type', 'geo_id', 'period_start', 'period', 'metric', 'source', name='uq_market_metrics')
    )
    with op.batch_alter_table('market_metrics', schema=None) as batch_op:
        batch_op.create_index('ix_market_metrics_lookup', ['geo_type', 'geo_id', 'metric', 'period_start'], unique=False)

    op.create_table('pipeline_runs',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('job', sa.Text(), nullable=False),
    sa.Column('started_at', sa.Text(), nullable=False),
    sa.Column('finished_at', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('items_seen', sa.Integer(), nullable=False),
    sa.Column('items_upserted', sa.Integer(), nullable=False),
    sa.Column('events_emitted', sa.Integer(), nullable=False),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.create_index('ix_pipeline_runs_job_started', ['job', 'started_at'], unique=False)

    op.create_table('price_index',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('geo_type', sa.Text(), nullable=False),
    sa.Column('geo_id', sa.Text(), nullable=False),
    sa.Column('month', sa.Text(), nullable=False),
    sa.Column('index_value', sa.Float(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('geo_type', 'geo_id', 'month', 'source', name='uq_price_index')
    )
    op.create_table('properties',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('address_norm', sa.Text(), nullable=False),
    sa.Column('unit', sa.Text(), nullable=False),
    sa.Column('street', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('zip', sa.Text(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('beds', sa.Integer(), nullable=True),
    sa.Column('baths', sa.Float(), nullable=True),
    sa.Column('sqft', sa.Integer(), nullable=True),
    sa.Column('lot_sqft', sa.Integer(), nullable=True),
    sa.Column('year_built', sa.Integer(), nullable=True),
    sa.Column('property_type', sa.Text(), nullable=False),
    sa.Column('apn', sa.Text(), nullable=True),
    sa.Column('assessor_sqft', sa.Integer(), nullable=True),
    sa.Column('condition_tag', sa.Text(), nullable=True),
    sa.Column('condition_notes', sa.Text(), nullable=True),
    sa.Column('source_ids', sa.JSON(), nullable=False),
    sa.Column('price_history', sa.JSON(), nullable=True),
    sa.Column('price_history_fetched_at', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('address_norm', 'zip', 'unit', name='uq_properties_address')
    )
    with op.batch_alter_table('properties', schema=None) as batch_op:
        batch_op.create_index('ix_properties_lat_lon', ['lat', 'lon'], unique=False)
        batch_op.create_index('ix_properties_zip', ['zip'], unique=False)

    op.create_table('rate_snapshots',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('series', sa.Text(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date', 'series', name='uq_rate_snapshots')
    )
    op.create_table('school_districts',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('geoid', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('lo_grade', sa.Text(), nullable=True),
    sa.Column('hi_grade', sa.Text(), nullable=True),
    sa.Column('geometry_json', sa.Text(), nullable=False),
    sa.Column('bbox_lat_min', sa.Float(), nullable=False),
    sa.Column('bbox_lat_max', sa.Float(), nullable=False),
    sa.Column('bbox_lon_min', sa.Float(), nullable=False),
    sa.Column('bbox_lon_max', sa.Float(), nullable=False),
    sa.Column('school_year', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('geoid')
    )
    with op.batch_alter_table('school_districts', schema=None) as batch_op:
        batch_op.create_index('ix_school_districts_bbox', ['bbox_lat_min', 'bbox_lat_max', 'bbox_lon_min', 'bbox_lon_max'], unique=False)

    op.create_table('schools',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('nces_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('level', sa.Text(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('district', sa.Text(), nullable=True),
    sa.Column('county', sa.Text(), nullable=True),
    sa.Column('zip', sa.Text(), nullable=True),
    sa.Column('leaid', sa.Text(), nullable=True),
    sa.Column('is_charter', sa.Boolean(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('pct_met', sa.Float(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nces_id')
    )
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.create_index('ix_schools_lat_lon', ['lat', 'lon'], unique=False)
        batch_op.create_index('ix_schools_leaid', ['leaid'], unique=False)
        batch_op.create_index('ix_schools_level', ['level'], unique=False)

    op.create_table('settings',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('avm_snapshots',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.Column('low', sa.Integer(), nullable=True),
    sa.Column('high', sa.Integer(), nullable=True),
    sa.Column('as_of', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'source', 'as_of', name='uq_avm_snapshots')
    )
    op.create_table('cma_runs',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('estimate', sa.Integer(), nullable=True),
    sa.Column('low', sa.Integer(), nullable=True),
    sa.Column('high', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Text(), nullable=True),
    sa.Column('index_source', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('hazard_flags',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('hazard', sa.Text(), nullable=False),
    sa.Column('zone_value', sa.Text(), nullable=True),
    sa.Column('checked_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'hazard', name='uq_hazard_flags')
    )
    op.create_table('listing_groups',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('first_list_date', sa.Text(), nullable=True),
    sa.Column('cumulative_dom', sa.Integer(), nullable=True),
    sa.Column('episode_count', sa.Integer(), nullable=False),
    sa.Column('ended_by', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('school_rating_snapshots',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('school_id', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('rating_10', sa.Float(), nullable=True),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('as_of', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('school_id', 'source', name='uq_school_rating_snapshots')
    )
    with op.batch_alter_table('school_rating_snapshots', schema=None) as batch_op:
        batch_op.create_index('ix_school_rating_snapshots_school', ['school_id'], unique=False)

    op.create_table('listings',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('listing_group_id', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_listing_id', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('list_price', sa.Integer(), nullable=True),
    sa.Column('original_list_price', sa.Integer(), nullable=True),
    sa.Column('list_date', sa.Text(), nullable=True),
    sa.Column('pending_date', sa.Text(), nullable=True),
    sa.Column('sold_date', sa.Text(), nullable=True),
    sa.Column('delist_date', sa.Text(), nullable=True),
    sa.Column('sold_price', sa.Integer(), nullable=True),
    sa.Column('dom_source', sa.Integer(), nullable=True),
    sa.Column('offer_due_at', sa.Text(), nullable=True),
    sa.Column('photo_urls', sa.JSON(), nullable=False),
    sa.Column('photo_paths', sa.JSON(), nullable=False),
    sa.Column('raw', sa.JSON(), nullable=False),
    sa.Column('viewed_at', sa.Text(), nullable=True),
    sa.Column('first_seen', sa.Text(), nullable=False),
    sa.Column('last_seen', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_group_id'], ['listing_groups.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_listing_id', name='uq_listings_source_id')
    )
    with op.batch_alter_table('listings', schema=None) as batch_op:
        batch_op.create_index('ix_listings_listing_group_id', ['listing_group_id'], unique=False)
        batch_op.create_index('ix_listings_property_id', ['property_id'], unique=False)
        batch_op.create_index('ix_listings_status', ['status'], unique=False)

    op.create_table('deals',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('accepted_on', sa.Text(), nullable=False),
    sa.Column('purchase_price', sa.Integer(), nullable=True),
    sa.Column('emd_amount', sa.Integer(), nullable=True),
    sa.Column('emd_sent_on', sa.Text(), nullable=True),
    sa.Column('emd_business_days', sa.Integer(), nullable=True),
    sa.Column('close_of_escrow_on', sa.Text(), nullable=True),
    sa.Column('investigation_days', sa.Integer(), nullable=True),
    sa.Column('appraisal_days', sa.Integer(), nullable=True),
    sa.Column('loan_days', sa.Integer(), nullable=True),
    sa.Column('financed', sa.Integer(), nullable=False),
    sa.Column('loan_type', sa.Text(), nullable=True),
    sa.Column('escrow_company', sa.Text(), nullable=True),
    sa.Column('escrow_number', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('checklist', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', name='uq_deals_listing')
    )
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.create_index('ix_deals_status', ['status'], unique=False)

    op.create_table('listing_events',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('observed_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', 'event_type', 'observed_at', 'new_value', name='uq_listing_events')
    )
    with op.batch_alter_table('listing_events', schema=None) as batch_op:
        batch_op.create_index('ix_listing_events_listing_observed', ['listing_id', 'observed_at'], unique=False)

    op.create_table('open_houses',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('start_at', sa.Text(), nullable=False),
    sa.Column('end_at', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('href', sa.Text(), nullable=True),
    sa.Column('methods', sa.JSON(), nullable=False),
    sa.Column('scheduled_at', sa.Text(), nullable=True),
    sa.Column('cancelled_at', sa.Text(), nullable=True),
    sa.Column('first_seen', sa.Text(), nullable=False),
    sa.Column('last_seen', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', 'source', 'start_at', name='uq_open_houses_slot')
    )
    with op.batch_alter_table('open_houses', schema=None) as batch_op:
        batch_op.create_index('ix_open_houses_start_at', ['start_at'], unique=False)

    op.create_table('property_tours',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=True),
    sa.Column('toured_on', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('checklist', sa.JSON(), nullable=False),
    sa.Column('agent_answers', sa.JSON(), nullable=False),
    sa.Column('gut_score', sa.Integer(), nullable=True),
    sa.Column('verdict', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('repair_low', sa.Integer(), nullable=True),
    sa.Column('repair_high', sa.Integer(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'toured_on', name='uq_property_tours_visit')
    )
    with op.batch_alter_table('property_tours', schema=None) as batch_op:
        batch_op.create_index('ix_property_tours_property_id', ['property_id'], unique=False)

    op.create_table('sales',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('property_id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=True),
    sa.Column('sale_date', sa.Text(), nullable=False),
    sa.Column('sale_price', sa.Integer(), nullable=False),
    sa.Column('list_price_at_sale', sa.Integer(), nullable=True),
    sa.Column('original_list_price', sa.Integer(), nullable=True),
    sa.Column('sp_lp', sa.Float(), nullable=True),
    sa.Column('dom', sa.Integer(), nullable=True),
    sa.Column('cumulative_dom', sa.Integer(), nullable=True),
    sa.Column('had_price_cut', sa.Boolean(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'sale_date', name='uq_sales_property_date')
    )
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.create_index('ix_sales_sale_date', ['sale_date'], unique=False)

    op.create_table('tracked_listings',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=False),
    sa.Column('stage', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('disclosure_checklist', sa.JSON(), nullable=False),
    sa.Column('my_max_bid', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', name='uq_tracked_listings_listing')
    )
    op.create_table('alerts',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=True),
    sa.Column('tracked_listing_id', sa.Text(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('dedup_key', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('delivered_at', sa.Text(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.ForeignKeyConstraint(['tracked_listing_id'], ['tracked_listings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedup_key', name='uq_alerts_dedup_key')
    )
    op.create_table('cma_comps',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('cma_run_id', sa.Text(), nullable=False),
    sa.Column('sale_id', sa.Text(), nullable=False),
    sa.Column('similarity_score', sa.Float(), nullable=False),
    sa.Column('auto_selected', sa.Boolean(), nullable=False),
    sa.Column('included', sa.Boolean(), nullable=False),
    sa.Column('time_adj_factor', sa.Float(), nullable=True),
    sa.Column('adjustments', sa.JSON(), nullable=False),
    sa.Column('adjusted_price', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cma_run_id'], ['cma_runs.id'], ),
    sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cma_run_id', 'sale_id', name='uq_cma_comps')
    )
    op.create_table('contacts',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('deal_id', sa.Text(), nullable=True),
    sa.Column('listing_id', sa.Text(), nullable=True),
    sa.Column('company', sa.Text(), nullable=True),
    sa.Column('role', sa.Text(), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.create_index('ix_contacts_deal_id', ['deal_id'], unique=False)
        batch_op.create_index('ix_contacts_listing_id', ['listing_id'], unique=False)

    op.create_table('preapprovals',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('contact_id', sa.Text(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('rate', sa.Float(), nullable=True),
    sa.Column('expires_on', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    _seed()


def _seed() -> None:
    bind = op.get_bind()
    if not bind.execute(
        sa.text("SELECT 1 FROM buyer_profile WHERE id = 'default'")
    ).first():
        bind.execute(
            sa.text(
                "INSERT INTO buyer_profile "
                "(id, cash_available, down_payment, rate_assumption, "
                " appraisal_gap_tolerance_pct, insurance_monthly_est, "
                " include_earthquake_ins, target_zips, updated_at) "
                "VALUES ('default', 0, 0, NULL, 0.05, 250, 0, '[]', "
                "        strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))"
            )
        )
    if not bind.execute(
        sa.text("SELECT 1 FROM settings WHERE key = 'alert_rules'")
    ).first():
        bind.execute(
            sa.text(
                "INSERT INTO settings (key, value, updated_at) "
                "VALUES ('alert_rules', :value, "
                "        strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))"
            ),
            {"value": json.dumps(ALERT_RULES)},
        )


def downgrade() -> None:
    op.drop_table('preapprovals')
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_index('ix_contacts_listing_id')
        batch_op.drop_index('ix_contacts_deal_id')

    op.drop_table('contacts')
    op.drop_table('cma_comps')
    op.drop_table('alerts')
    op.drop_table('tracked_listings')
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.drop_index('ix_sales_sale_date')

    op.drop_table('sales')
    with op.batch_alter_table('property_tours', schema=None) as batch_op:
        batch_op.drop_index('ix_property_tours_property_id')

    op.drop_table('property_tours')
    with op.batch_alter_table('open_houses', schema=None) as batch_op:
        batch_op.drop_index('ix_open_houses_start_at')

    op.drop_table('open_houses')
    with op.batch_alter_table('listing_events', schema=None) as batch_op:
        batch_op.drop_index('ix_listing_events_listing_observed')

    op.drop_table('listing_events')
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.drop_index('ix_deals_status')

    op.drop_table('deals')
    with op.batch_alter_table('listings', schema=None) as batch_op:
        batch_op.drop_index('ix_listings_status')
        batch_op.drop_index('ix_listings_property_id')
        batch_op.drop_index('ix_listings_listing_group_id')

    op.drop_table('listings')
    with op.batch_alter_table('school_rating_snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_school_rating_snapshots_school')

    op.drop_table('school_rating_snapshots')
    op.drop_table('listing_groups')
    op.drop_table('hazard_flags')
    op.drop_table('cma_runs')
    op.drop_table('avm_snapshots')
    op.drop_table('settings')
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_index('ix_schools_level')
        batch_op.drop_index('ix_schools_leaid')
        batch_op.drop_index('ix_schools_lat_lon')

    op.drop_table('schools')
    with op.batch_alter_table('school_districts', schema=None) as batch_op:
        batch_op.drop_index('ix_school_districts_bbox')

    op.drop_table('school_districts')
    op.drop_table('rate_snapshots')
    with op.batch_alter_table('properties', schema=None) as batch_op:
        batch_op.drop_index('ix_properties_zip')
        batch_op.drop_index('ix_properties_lat_lon')

    op.drop_table('properties')
    op.drop_table('price_index')
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_pipeline_runs_job_started')

    op.drop_table('pipeline_runs')
    with op.batch_alter_table('market_metrics', schema=None) as batch_op:
        batch_op.drop_index('ix_market_metrics_lookup')

    op.drop_table('market_metrics')
    op.drop_table('buyer_profile')
