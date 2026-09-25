# References

The SRS is the primary specification for this report. The other references are the external specifications, algorithms and technical documentation that the SupportNova implementation actually uses; each entry states where it is used. Internal project documents (README.md, AI_USAGE.md, docs/dataset.md, the reports in `reports/` and the Knowledge Base documents of the fictional Lumora Home Technologies) are cited in the text by their repository path and are not repeated here.

## Primary Specification

[1] Aptech Limited, *SupportNova — Customer Complaint Resolution Intelligence: Software Requirements Specification*, Generative AI PowerPlay, theme ResponseX Intelligence. Issued to the participating teams; kept locally as `docs/SupportNova-Generative AI PowerPlay_SRS.pdf` and not redistributed in the public repository (`.gitignore` excludes `docs/*.pdf`).

## Algorithms and Methods

[2] S. Robertson and H. Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond," *Foundations and Trends in Information Retrieval*, vol. 3, no. 4, pp. 333–389, 2009. Used for the Okapi BM25 lexical index in `backend/src/supportnova/knowledge_base/bm25.py`.

[3] G. V. Cormack, C. L. A. Clarke and S. Büttcher, "Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods," in *Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval*, 2009, pp. 758–759. Used for fusing the lexical and vector rankings (constant k = 60) in `knowledge_base/retriever.py`.

[4] K. Weinberger, A. Dasgupta, J. Langford, A. Smola and J. Attenberg, "Feature Hashing for Large Scale Multitask Learning," in *Proceedings of the 26th International Conference on Machine Learning (ICML)*, 2009. Basis of the signed feature-hashing local embedder in `knowledge_base/embeddings.py`.

[5] P. Lewis, E. Perez, A. Piktus, F. Petroni, V. Karpukhin, N. Goyal, H. Küttler, M. Lewis, W. Yih, T. Rocktäschel, S. Riedel and D. Kiela, "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks," in *Advances in Neural Information Processing Systems 33 (NeurIPS)*, 2020. Origin of the retrieval-augmented generation (RAG) pattern required by the SRS and applied in Chapter 9.

[6] N. Provos and D. Mazières, "A Future-Adaptable Password Scheme," in *Proceedings of the 1999 USENIX Annual Technical Conference, FREENIX Track*, 1999. The bcrypt password hashing used in `backend/src/supportnova/security/auth.py`.

[7] H. P. Luhn, "Computer for Verifying Numbers," U.S. Patent 2,950,048, 1960. The Luhn checksum used to confirm payment-card numbers before redaction in `backend/src/supportnova/security/pii.py`.

## Standards and Security Guidance

[8] M. Jones, J. Bradley and N. Sakimura, "JSON Web Token (JWT)," IETF RFC 7519, May 2015. Signed access tokens (HS256) in `security/auth.py`.

[9] JSON Schema, *JSON Schema: A Media Type for Describing JSON Documents*, Draft 2020-12. https://json-schema.org/draft/2020-12. Dialect of `schemas/ai/complaint_analysis.v1.schema.json` and `schemas/ai/customer_communication.v1.schema.json`.

[10] OWASP Foundation, "CSV Injection." https://owasp.org/www-community/attacks/CSV_Injection. Formula neutralisation in CSV and Excel exports (`backend/src/supportnova/reporting/exports.py`).

## GenAI Provider Documentation

[11] OpenAI, "Structured Outputs," OpenAI API documentation. https://platform.openai.com/docs/guides/structured-outputs. The `response_format` JSON-schema mode used by the default provider adapter (`genai_pipeline/providers/http_providers.py`).

[12] Anthropic, Claude API documentation. https://docs.anthropic.com/. Messages API with JSON-schema output format used by `genai_pipeline/providers/anthropic_provider.py`.

[13] Google, Gemini API documentation. https://ai.google.dev/gemini-api/docs. Structured JSON responses (`responseJsonSchema`) used by the Gemini adapter in `genai_pipeline/providers/http_providers.py`.

## Frameworks and Libraries

[14] FastAPI documentation. https://fastapi.tiangolo.com/. Backend web framework (version 0.141.1).

[15] Pydantic documentation. https://docs.pydantic.dev/. Request, settings and output validation (version 2.13.5).

[16] SQLAlchemy 2.0 documentation. https://docs.sqlalchemy.org/en/20/. Object-relational mapping (version 2.0.54).

[17] Alembic documentation. https://alembic.sqlalchemy.org/. Database migrations `0001_initial_schema` and `0002_drop_mock_flags` (version 1.20.0).

[18] PostgreSQL Global Development Group, *PostgreSQL 17 Documentation*. https://www.postgresql.org/docs/17/. Application database, including the trigger that makes the audit log append-only.

[19] PyMuPDF documentation. https://pymupdf.readthedocs.io/. PDF parsing in `backend/src/supportnova/document_processing/parsers.py` (version 1.28.2).

[20] python-docx documentation. https://python-docx.readthedocs.io/. DOCX parsing (version 1.2.0).

[21] React documentation. https://react.dev/. Frontend library (version 19).

[22] Vite documentation. https://vite.dev/. Frontend build tool.

[23] TanStack Query documentation. https://tanstack.com/query/latest. Server-state management in the frontend.

[24] Tailwind CSS documentation. https://tailwindcss.com/docs. Frontend styling (version 4).

[25] Mermaid documentation. https://mermaid.js.org/. Source format of the diagrams in this report (`documentation/diagrams/**/*.mmd`, rendered with Mermaid 11.4.1).
