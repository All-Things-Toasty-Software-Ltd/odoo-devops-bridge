.. Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

====================================================================
 DevOps Project Bridge - Technical Documentation
====================================================================

.. contents::
   :local:
   :depth: 2

Overview
========

**DevOps Project Bridge** connects Odoo Project (Community Edition) with GitHub,
GitLab, and JetBrains YouTrack, keeping tasks, pull/merge requests, comments,
and milestones synchronized in both directions.

This documentation set is organized as follows:

- :doc:`architecture` - models, sequence diagrams, and the webhook processing
  pipeline for developers or technical evaluators.
- :doc:`admin_guide` - step-by-step setup for GitHub Enterprise, GitLab
  Self-Hosted, and YouTrack Standalone, written for DevOps Administrators.
- :doc:`user_guide` - a walkthrough for internal Odoo users connecting their
  personal credentials and working with synced tasks and pull requests.
- :doc:`webhook_setup` - provider-by-provider webhook configuration
  instructions.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   architecture
   admin_guide
   user_guide
   webhook_setup

Module Metadata
================

============================  ============================================
Technical name                 ``odoo_devops_bridge``
Odoo compatibility             SaaS 19.2 / Community Edition 19.x
License                        LGPL-3 (Lesser GNU Public License v3.0)
Dependencies                   ``base``, ``web``, ``project``, ``mail``
Author                          All Things Toasty Software Ltd
============================  ============================================

Getting Help
=============

For installation issues, consult :doc:`admin_guide`. For synchronization
behavior or day-to-day usage questions, consult :doc:`user_guide`. For
anything related to source code or extending the module, start with
:doc:`architecture`.
