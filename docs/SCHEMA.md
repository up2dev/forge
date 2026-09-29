# Schéma de la base

Généré depuis les modèles réels (`forge/security/models.py`,
`forge/audit.py`, `forge/storage/models.py`,
`example_app/models/*.py`) — à régénérer si les modèles changent,
pas maintenu à la main.

```mermaid
erDiagram
    USERS ||--o{ ACCESS_TOKENS : has
    USERS ||--o{ USER_MFA_METHODS : has
    USERS ||--o{ MFA_PENDING_TOKENS : has
    USERS ||--o{ MFA_EMAIL_CODES : has
    USERS ||--o{ PASSWORD_RESET_TOKENS : has
    USERS ||--o{ STORAGE_FILES : owns
    USERS ||--o{ NOTES : owns
    USERS }o--o{ ROLES : user_role
    ROLES }o--o{ PERMISSIONS : role_permission
    AUTHORS ||--o{ BOOKS : writes

    USERS {
        int id PK
        string login
        string email
        string password_hash
        bool is_active
    }
    ROLES {
        int id PK
        string uid
        string name
    }
    PERMISSIONS {
        int id PK
        string uid
        string name
    }
    ACCESS_TOKENS {
        int id PK
        int user_id FK
        string token_hash
        string name
        datetime expires_at
    }
    USER_MFA_METHODS {
        int id PK
        int user_id FK
        string method
        string secret
        datetime confirmed_at
    }
    MFA_PENDING_TOKENS {
        int id PK
        string token_hash
        int user_id FK
        string intent
        datetime expires_at
    }
    MFA_EMAIL_CODES {
        int id PK
        int user_id FK
        string code_hash
        datetime expires_at
    }
    PASSWORD_RESET_TOKENS {
        int id PK
        string token_hash
        int user_id FK
        datetime expires_at
    }
    ACTIVITY_LOG {
        int id PK
        string model
        int record_id
        string action
        int actor_id
        string changes
    }
    STORAGE_FILES {
        int id PK
        string filename
        string content_type
        int total_bytes
        int received_bytes
        string storage_key
        datetime completed_at
        int owner_id FK
    }
    AUTHORS {
        int id PK
        string name
    }
    BOOKS {
        int id PK
        string title
        int year
        int author_id FK
    }
    NOTES {
        int id PK
        string content
        int user_id FK
    }
```

Notes :
- `ACTIVITY_LOG.actor_id` n'a **pas** de contrainte FK — volontaire,
  pour garder l'historique d'audit même si l'utilisateur qui a fait
  l'action est supprimé ensuite.
- `user_role` et `role_permission` sont les tables pivot des relations
  N-N (RBAC) — pas de ligne propre dans ce schéma, juste les deux
  colonnes de clé étrangère composant la clé primaire.
- `AUTHORS`/`BOOKS`/`NOTES` sont l'app d'exemple (`example_app/`), pas
  le framework — gardées ici pour la vue d'ensemble complète.
