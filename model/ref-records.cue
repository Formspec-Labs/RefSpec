{
  "modelVersion": "1.0",
  "description": "Authoritative JSON-compatible CUE source for REF-owned JSON Binding structures.",
  "schemas": {
    "capture.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/capture.schema.json",
      "title": "REF Capture",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        },
        {
          "if": {
            "properties": {
              "acquisitionStatus": {
                "const": "success"
              }
            },
            "required": [
              "acquisitionStatus"
            ]
          },
          "then": {
            "required": [
              "byteDigest",
              "byteLength",
              "storageReference"
            ],
            "properties": {
              "byteLength": {
                "minimum": 1
              }
            }
          }
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "source",
        "sourceLocator",
        "requestMethod",
        "safeRequestParameters",
        "retrievalStartedAt",
        "retrievalEndedAt",
        "responseStatus",
        "requestHeaders",
        "responseHeaders",
        "acquisitionStatus",
        "contentPreservation",
        "completeness",
        "acquisitionActivity",
        "runReceipt",
        "accessScopeRefs",
        "retentionPolicyRefs",
        "rightsExpressionRefs"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:Capture"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "source": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "sourceLocator": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "requestMethod": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "safeRequestParameters": {
          "type": "object",
          "additionalProperties": {
            "oneOf": [
              {
                "type": "string"
              },
              {
                "type": "array",
                "items": {
                  "type": "string"
                }
              }
            ]
          }
        },
        "retrievalStartedAt": {
          "type": "string",
          "format": "date-time"
        },
        "retrievalEndedAt": {
          "type": "string",
          "format": "date-time"
        },
        "responseStatus": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "requestHeaders": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
        "responseHeaders": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
        "mediaType": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "acquisitionStatus": {
          "enum": [
            "success",
            "partial",
            "failure"
          ]
        },
        "byteDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "byteLength": {
          "type": "integer",
          "minimum": 0
        },
        "storageReference": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "contentPreservation": {
          "enum": [
            "exactBytes",
            "canonicalResponse",
            "exactApplicationPayload"
          ]
        },
        "preservationLimit": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "completeness": {
          "type": "object",
          "required": [
            "complete",
            "pagination",
            "retries",
            "exclusions"
          ],
          "properties": {
            "complete": {
              "type": "boolean"
            },
            "pagination": {
              "type": "object"
            },
            "retries": {
              "type": "array",
              "items": {
                "type": "object"
              }
            },
            "exclusions": {
              "type": "array",
              "items": {
                "type": "object"
              }
            }
          },
          "additionalProperties": false
        },
        "acquisitionActivity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "runReceipt": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "accessScopeRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "retentionPolicyRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "rightsExpressionRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        }
      },
      "unevaluatedProperties": false
    },
    "common.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/common.schema.json",
      "title": "REF JSON Binding 1.0 common definitions",
      "$defs": {
        "absoluteIri": {
          "type": "string",
          "format": "uri",
          "pattern": "^[A-Za-z][A-Za-z0-9+.-]*:[^\\s]+$"
        },
        "bcp47Language": {
          "type": "string",
          "pattern": "^(?:(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|[A-Za-z]{5,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*(?:-[xX](?:-[A-Za-z0-9]{1,8})+)?|[xX](?:-[A-Za-z0-9]{1,8})+|[eE][nN]-[gG][bB]-[oO][eE][dD]|[iI]-(?:[aA][mM][iI]|[bB][nN][nN]|[dD][eE][fF][aA][uU][lL][tT]|[eE][nN][oO][cC][hH][iI][aA][nN]|[hH][aA][kK]|[kK][lL][iI][nN][gG][oO][nN]|[lL][uU][xX]|[mM][iI][nN][gG][oO]|[nN][aA][vV][aA][jJ][oO]|[pP][wW][nN]|[tT][aA][oO]|[tT][aA][yY]|[tT][sS][uU])|[sS][gG][nN]-(?:[bB][eE]-[fF][rR]|[bB][eE]-[nN][lL]|[cC][hH]-[dD][eE])|[aA][rR][tT]-[lL][oO][jJ][bB][aA][nN]|[cC][eE][lL]-[gG][aA][uU][lL][iI][sS][hH]|[nN][oO]-(?:[bB][oO][kK]|[nN][yY][nN])|[zZ][hH]-(?:[gG][uU][oO][yY][uU]|[hH][aA][kK][kK][aA]|[mM][iI][nN]|[mM][iI][nN]-[nN][aA][nN]|[xX][iI][aA][nN][gG]))$"
        },
        "digest": {
          "type": "string",
          "pattern": "^sha256:[0-9a-f]{64}$"
        },
        "canonicalDecimal": {
          "type": "string",
          "pattern": "^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$"
        },
        "nonEmptyString": {
          "type": "string",
          "minLength": 1
        },
        "stringList": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "#/$defs/nonEmptyString"
          }
        },
        "iriList": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "#/$defs/absoluteIri"
          }
        },
        "controlledIdentifier": {
          "type": "object",
          "required": [
            "value",
            "kind",
            "authorityUri",
            "sourceUri",
            "sourcePath",
            "observedAt",
            "sourceDigest"
          ],
          "properties": {
            "value": {
              "$ref": "#/$defs/nonEmptyString"
            },
            "kind": {
              "$ref": "#/$defs/nonEmptyString"
            },
            "authorityUri": {
              "$ref": "#/$defs/absoluteIri"
            },
            "sourceUri": {
              "$ref": "#/$defs/absoluteIri"
            },
            "sourcePath": {
              "$ref": "#/$defs/nonEmptyString"
            },
            "observedAt": {
              "type": "string",
              "format": "date-time"
            },
            "effectiveFrom": {
              "anyOf": [
                {
                  "type": "string",
                  "format": "date"
                },
                {
                  "type": "string",
                  "format": "date-time"
                }
              ]
            },
            "effectiveThrough": {
              "anyOf": [
                {
                  "type": "string",
                  "format": "date"
                },
                {
                  "type": "string",
                  "format": "date-time"
                }
              ]
            },
            "sourceDigest": {
              "$ref": "#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "identifierReference": {
          "type": "object",
          "required": [
            "id"
          ],
          "properties": {
            "id": {
              "$ref": "#/$defs/absoluteIri"
            }
          },
          "additionalProperties": false
        },
        "digestReference": {
          "type": "object",
          "required": [
            "id",
            "digest"
          ],
          "properties": {
            "id": {
              "$ref": "#/$defs/absoluteIri"
            },
            "digest": {
              "$ref": "#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "versionedDigestReference": {
          "type": "object",
          "required": [
            "id",
            "version",
            "digest"
          ],
          "properties": {
            "id": {
              "$ref": "#/$defs/absoluteIri"
            },
            "version": {
              "$ref": "#/$defs/nonEmptyString"
            },
            "digest": {
              "$ref": "#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "componentPin": {
          "type": "object",
          "required": [
            "id",
            "revision",
            "digest"
          ],
          "properties": {
            "id": {
              "$ref": "#/$defs/absoluteIri"
            },
            "revision": {
              "$ref": "#/$defs/nonEmptyString"
            },
            "digest": {
              "$ref": "#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "commonRecordProperties": {
          "type": "object",
          "required": [
            "id",
            "type",
            "recordedAt",
            "recordedBy",
            "schemaVersion",
            "operationalState"
          ],
          "properties": {
            "id": {
              "$ref": "#/$defs/absoluteIri"
            },
            "type": {
              "$ref": "#/$defs/absoluteIri"
            },
            "recordedAt": {
              "type": "string",
              "format": "date-time"
            },
            "recordedBy": {
              "$ref": "#/$defs/absoluteIri"
            },
            "schemaVersion": {
              "const": "1.0"
            },
            "operationalState": {
              "$ref": "#/$defs/nonEmptyString"
            }
          }
        }
      }
    },
    "concept-proposal.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/concept-proposal.schema.json",
      "title": "REF ConceptProposal",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "facet",
        "wording",
        "evidenceAddresses",
        "activity",
        "workflowState",
        "governanceQueue",
        "supersessionHistory"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:ConceptProposal"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "facet": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "wording": {
          "type": "object",
          "required": [
            "value",
            "language"
          ],
          "properties": {
            "value": {
              "$ref": "common.schema.json#/$defs/nonEmptyString"
            },
            "language": {
              "$ref": "common.schema.json#/$defs/bcp47Language"
            }
          },
          "additionalProperties": false
        },
        "evidenceAddresses": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/absoluteIri"
          }
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "workflowState": {
          "enum": [
            "submitted",
            "underReview",
            "acceptedForPromotion",
            "rejected",
            "withdrawn",
            "superseded"
          ]
        },
        "governanceQueue": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "proposedAnchors": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "proposedMappingRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "supersessionHistory": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        }
      },
      "unevaluatedProperties": false
    },
    "enrichment-configuration.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/enrichment-configuration.schema.json",
      "title": "REF EnrichmentConfiguration",
      "$defs": {
        "pinArray": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/componentPin"
          }
        },
        "budgetLimit": {
          "oneOf": [
            {
              "type": "integer",
              "minimum": 0
            },
            {
              "const": "unlimited"
            }
          ]
        }
      },
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "implementation",
        "enrichmentProfile",
        "outputProfile",
        "acceptancePolicy",
        "schemas",
        "inputCorpora",
        "vocabulary",
        "indexes",
        "candidateChannels",
        "models",
        "prompts",
        "toolPolicies",
        "budgets",
        "determinism",
        "otherBehaviorPins",
        "secretVersionRefs"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:EnrichmentConfiguration"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "implementation": {
          "type": "object",
          "required": [
            "id",
            "revision",
            "build",
            "runtime",
            "dependencyLockDigest"
          ],
          "properties": {
            "id": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "revision": {
              "$ref": "common.schema.json#/$defs/nonEmptyString"
            },
            "build": {
              "$ref": "common.schema.json#/$defs/nonEmptyString"
            },
            "runtime": {
              "$ref": "common.schema.json#/$defs/componentPin"
            },
            "dependencyLockDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "enrichmentProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "outputProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "acceptancePolicy": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "schemas": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/versionedDigestReference"
          }
        },
        "inputCorpora": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/versionedDigestReference"
          }
        },
        "vocabulary": {
          "type": "object",
          "required": [
            "referenceResourceReleases",
            "registryImportSnapshots",
            "mappingReleases",
            "mappingSnapshots",
            "candidateTargetUniverseDigest",
            "registryDeploymentDecisions"
          ],
          "properties": {
            "referenceResourceReleases": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "registryImportSnapshots": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digestReference"
              }
            },
            "mappingReleases": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "mappingSnapshots": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digestReference"
              }
            },
            "candidateTargetUniverseDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "registryDeploymentDecisions": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digestReference"
              }
            }
          },
          "additionalProperties": false
        },
        "indexes": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "expressionCorpusSnapshot",
              "lookupIndexManifest",
              "indexedExpressionCorpusDigest",
              "indexedRepresentationVersion",
              "normalizationPolicy"
            ],
            "properties": {
              "expressionCorpusSnapshot": {
                "description": "Exact RefSpec-owned logical expression-corpus snapshot used to build the lookup index.",
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "lookupIndexManifest": {
                "description": "Exact consumer-owned manifest for the physical lookup index.",
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "indexedExpressionCorpusDigest": {
                "$ref": "common.schema.json#/$defs/digest"
              },
              "indexedRepresentationVersion": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "normalizationPolicy": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "additionalProperties": false
          }
        },
        "candidateChannels": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "retriever",
              "queryConstruction",
              "ordering",
              "fusion",
              "deduplication",
              "quota",
              "truncation",
              "fallbackPolicy"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "retriever": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "queryConstruction": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "ordering": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "fusion": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "deduplication": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "quota": {
                "type": "object",
                "required": [
                  "maximumCandidates",
                  "policy"
                ],
                "properties": {
                  "maximumCandidates": {
                    "type": "integer",
                    "minimum": 1
                  },
                  "policy": {
                    "$ref": "common.schema.json#/$defs/componentPin"
                  }
                },
                "additionalProperties": false
              },
              "truncation": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "fallbackPolicy": {
                "$ref": "common.schema.json#/$defs/componentPin"
              }
            },
            "additionalProperties": false
          }
        },
        "models": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "revision",
              "providerConfiguration",
              "endpointConfiguration",
              "inferenceParameters",
              "structuredOutputSchema"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "revision": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "providerConfiguration": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "endpointConfiguration": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "inferenceParameters": {
                "type": "object",
                "additionalProperties": {
                  "oneOf": [
                    {
                      "$ref": "common.schema.json#/$defs/nonEmptyString"
                    },
                    {
                      "type": "boolean"
                    },
                    {
                      "type": "integer"
                    }
                  ]
                }
              },
              "structuredOutputSchema": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "additionalProperties": false
          }
        },
        "prompts": {
          "$ref": "#/$defs/pinArray"
        },
        "toolPolicies": {
          "$ref": "#/$defs/pinArray"
        },
        "budgets": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "stage",
              "inputBytes",
              "outputBytes",
              "tokens",
              "milliseconds",
              "candidates",
              "costMicrounits"
            ],
            "properties": {
              "stage": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "inputBytes": {
                "$ref": "#/$defs/budgetLimit"
              },
              "outputBytes": {
                "$ref": "#/$defs/budgetLimit"
              },
              "tokens": {
                "$ref": "#/$defs/budgetLimit"
              },
              "milliseconds": {
                "$ref": "#/$defs/budgetLimit"
              },
              "candidates": {
                "$ref": "#/$defs/budgetLimit"
              },
              "costMicrounits": {
                "$ref": "#/$defs/budgetLimit"
              }
            },
            "additionalProperties": false
          }
        },
        "determinism": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "stage",
              "status",
              "replayControls"
            ],
            "properties": {
              "stage": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "status": {
                "enum": [
                  "deterministic",
                  "nondeterministic"
                ]
              },
              "seed": {
                "oneOf": [
                  {
                    "type": "integer"
                  },
                  {
                    "$ref": "common.schema.json#/$defs/nonEmptyString"
                  }
                ]
              },
              "replayControls": {
                "$ref": "common.schema.json#/$defs/componentPin"
              }
            },
            "additionalProperties": false
          }
        },
        "otherBehaviorPins": {
          "$ref": "#/$defs/pinArray"
        },
        "secretVersionRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        }
      },
      "unevaluatedProperties": false
    },
    "enrichment-deployment-decision.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/enrichment-deployment-decision.schema.json",
      "title": "REF EnrichmentDeploymentDecision",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "environment",
        "configuration",
        "evaluationResult",
        "outputProfile",
        "selectionState",
        "effectiveAt",
        "reason",
        "activity",
        "rulespecAttestationRefs",
        "localAdoptionRefs"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:EnrichmentDeploymentDecision"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "environment": {
          "type": "object",
          "required": [
            "id",
            "classification"
          ],
          "properties": {
            "id": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "classification": {
              "enum": [
                "production",
                "nonProduction"
              ]
            }
          },
          "additionalProperties": false
        },
        "configuration": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "evaluationResult": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "outputProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "selectionState": {
          "enum": [
            "staged",
            "selected",
            "deselected",
            "failed"
          ]
        },
        "effectiveAt": {
          "type": "string",
          "format": "date-time"
        },
        "reason": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "predecessorDecision": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "supersedingDecision": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "rulespecAttestationRefs": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "localAdoptionRefs": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "authorizationValidations": {
          "description": "Deprecated, non-authoritative caller report retained only for migration. A selected deployment is authorized only by a gate-issued ReleaseGraphValidationReceipt that binds a pinned Rulespec L4 evaluation.",
          "type": "array",
          "minItems": 2,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "authorizationRef",
              "kind",
              "validationReceipt",
              "validator",
              "validatedAt",
              "effective"
            ],
            "properties": {
              "authorizationRef": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "kind": {
                "enum": [
                  "rulespecAttestation",
                  "localAdoption"
                ]
              },
              "validationReceipt": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "validator": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "validatedAt": {
                "type": "string",
                "format": "date-time"
              },
              "effective": {
                "const": true
              }
            },
            "additionalProperties": false
          }
        }
      },
      "unevaluatedProperties": false
    },
    "enrichment-evaluation-result.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/enrichment-evaluation-result.schema.json",
      "title": "REF EnrichmentEvaluationResult",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "configuration",
        "sealedGoldManifest",
        "evaluationProtocol",
        "predeclaredMeasures",
        "thresholds",
        "configuredStrata",
        "exclusions",
        "uncertaintyMethod",
        "observedMeasures",
        "measurePopulations",
        "gates",
        "evaluator",
        "activity",
        "evaluatedAt",
        "outputArtifactDigests",
        "verdict"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:EnrichmentEvaluationResult"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "configuration": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "sealedGoldManifest": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "evaluationProtocol": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "predeclaredMeasures": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/absoluteIri"
          }
        },
        "thresholds": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "measure",
              "operator",
              "value"
            ],
            "properties": {
              "measure": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "operator": {
                "enum": [
                  "atLeast",
                  "atMost"
                ]
              },
              "value": {
                "$ref": "common.schema.json#/$defs/canonicalDecimal"
              }
            },
            "additionalProperties": false
          }
        },
        "configuredStrata": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "stratum",
              "minimumSampleSize",
              "observedSampleSize",
              "passed"
            ],
            "properties": {
              "stratum": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "minimumSampleSize": {
                "type": "integer",
                "minimum": 1
              },
              "observedSampleSize": {
                "type": "integer",
                "minimum": 0
              },
              "passed": {
                "type": "boolean"
              }
            },
            "additionalProperties": false
          }
        },
        "exclusions": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "uncertaintyMethod": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "observedMeasures": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "measure",
              "value",
              "uncertaintyLower",
              "uncertaintyUpper"
            ],
            "properties": {
              "measure": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "value": {
                "$ref": "common.schema.json#/$defs/canonicalDecimal"
              },
              "uncertaintyLower": {
                "$ref": "common.schema.json#/$defs/canonicalDecimal"
              },
              "uncertaintyUpper": {
                "$ref": "common.schema.json#/$defs/canonicalDecimal"
              }
            },
            "additionalProperties": false
          }
        },
        "measurePopulations": {
          "type": "array",
          "minItems": 3,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "measure",
              "populationKind",
              "includedExpectations",
              "excludedExpectations"
            ],
            "properties": {
              "measure": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "populationKind": {
                "enum": [
                  "reachableRegisteredCandidateRecall",
                  "targetAvailability",
                  "openSet"
                ]
              },
              "includedExpectations": {
                "$ref": "common.schema.json#/$defs/iriList"
              },
              "excludedExpectations": {
                "$ref": "common.schema.json#/$defs/iriList"
              }
            },
            "additionalProperties": false
          }
        },
        "gates": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "dimension",
              "subject",
              "passed",
              "reason"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "dimension": {
                "enum": [
                  "stage",
                  "source",
                  "subtype",
                  "facet",
                  "role",
                  "predicate",
                  "privacy",
                  "risk",
                  "latency",
                  "cost",
                  "product"
                ]
              },
              "subject": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "passed": {
                "type": "boolean"
              },
              "reason": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "additionalProperties": false
          }
        },
        "evaluator": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "evaluatedAt": {
          "type": "string",
          "format": "date-time"
        },
        "outputArtifactDigests": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digest"
          }
        },
        "verdict": {
          "enum": [
            "pass",
            "fail",
            "developmentOnly"
          ]
        }
      },
      "unevaluatedProperties": false
    },
    "enrichment-profile.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/enrichment-profile.schema.json",
      "title": "REF EnrichmentProfile",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "version",
        "contentDigest",
        "facets"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:EnrichmentProfile"
        },
        "version": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "contentDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "facets": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "iri",
              "label",
              "definition",
              "inclusionCues",
              "exclusionCues",
              "compatibleResourceRoutes",
              "compatibleAssignmentPredicates"
            ],
            "properties": {
              "iri": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "label": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "definition": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "inclusionCues": {
                "$ref": "common.schema.json#/$defs/stringList"
              },
              "exclusionCues": {
                "$ref": "common.schema.json#/$defs/stringList"
              },
              "compatibleResourceRoutes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "enum": [
                    "document",
                    "participation",
                    "container",
                    "entity",
                    "observation",
                    "event",
                    "externalReference"
                  ]
                }
              },
              "compatibleAssignmentPredicates": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "$ref": "common.schema.json#/$defs/absoluteIri"
                }
              }
            },
            "additionalProperties": false
          }
        }
      },
      "unevaluatedProperties": false
    },
    "indexed-vocabulary-expression.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/indexed-vocabulary-expression.schema.json",
      "title": "REF IndexedVocabularyExpression",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        },
        {
          "oneOf": [
            {
              "required": [
                "sourceProperty"
              ],
              "not": {
                "required": [
                  "sourcePath"
                ]
              }
            },
            {
              "required": [
                "sourcePath"
              ],
              "not": {
                "required": [
                  "sourceProperty"
                ]
              }
            }
          ]
        },
        {
          "oneOf": [
            {
              "required": [
                "language"
              ],
              "not": {
                "required": [
                  "datatype"
                ]
              }
            },
            {
              "required": [
                "datatype"
              ],
              "not": {
                "required": [
                  "language"
                ]
              }
            }
          ]
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "referenceResourceRelease",
        "registryImportSnapshot",
        "distributionArtifact",
        "scheme",
        "member",
        "semanticProperty",
        "originalLiteral",
        "normalizationPolicy",
        "indexedText",
        "indexedTextDigest",
        "indexedRepresentationVersion",
        "expressionCorpusSnapshot",
        "activity",
        "receipt"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:IndexedVocabularyExpression"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "referenceResourceRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "registryImportSnapshot": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "distributionArtifact": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "member": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "scheme": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "semanticProperty": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "sourceProperty": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "sourcePath": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "originalLiteral": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "language": {
          "$ref": "common.schema.json#/$defs/bcp47Language"
        },
        "datatype": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "normalizationPolicy": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "indexedText": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "indexedTextDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "indexedRepresentationVersion": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "expressionCorpusSnapshot": {
          "description": "Exact RefSpec-owned logical expression-corpus snapshot. This is not a physical lookup index.",
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "receipt": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        }
      },
      "unevaluatedProperties": false
    },
    "output-profile.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/output-profile.schema.json",
      "title": "REF OutputProfile",
      "$defs": {
        "permissionBase": {
          "type": "object",
          "required": [
            "facet",
            "assignmentRole",
            "candidateUse",
            "acceptedOutputUse"
          ],
          "properties": {
            "facet": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "assignmentRole": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "candidateUse": {
              "type": "boolean"
            },
            "acceptedOutputUse": {
              "type": "boolean"
            }
          }
        }
      },
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "version",
        "contentDigest",
        "enrichmentProfile",
        "acceptancePolicies",
        "publicationViews",
        "releasePermissions",
        "mappingPermissions",
        "openLabelPermissions"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:OutputProfile"
        },
        "version": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "contentDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "enrichmentProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "acceptancePolicies": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/versionedDigestReference"
          }
        },
        "publicationViews": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/versionedDigestReference"
          }
        },
        "releasePermissions": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "allOf": [
              {
                "$ref": "#/$defs/permissionBase"
              }
            ],
            "required": [
              "referenceResourceRelease",
              "registryImportSnapshot",
              "requiredImportFeatures"
            ],
            "properties": {
              "referenceResourceRelease": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              },
              "registryImportSnapshot": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "requiredImportFeatures": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "enum": [
                    "labels",
                    "languages",
                    "notation",
                    "notes",
                    "hierarchy",
                    "associativeRelations",
                    "mappings",
                    "status",
                    "replacements",
                    "identifiers",
                    "membership"
                  ]
                }
              }
            },
            "unevaluatedProperties": false
          }
        },
        "mappingPermissions": {
          "description": "Complete directed mapping-use rows. Every candidate-enabled row requires exact passing coverage for its mappingSnapshot.",
          "type": "array",
          "uniqueItems": true,
          "items": {
            "allOf": [
              {
                "$ref": "#/$defs/permissionBase"
              }
            ],
            "required": [
              "mappingSnapshot",
              "sourceRelease",
              "targetRelease",
              "relation",
              "direction"
            ],
            "properties": {
              "mappingSnapshot": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "sourceRelease": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              },
              "targetRelease": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              },
              "relation": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "direction": {
                "enum": [
                  "sourceToTarget",
                  "targetToSource"
                ]
              }
            },
            "unevaluatedProperties": false
          }
        },
        "openLabelPermissions": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "allOf": [
              {
                "$ref": "#/$defs/permissionBase"
              }
            ],
            "required": [
              "mode"
            ],
            "properties": {
              "mode": {
                "enum": [
                  "explicitLanguage",
                  "declaredDefaultLanguage"
                ]
              },
              "defaultLanguage": {
                "$ref": "common.schema.json#/$defs/bcp47Language"
              }
            },
            "if": {
              "properties": {
                "mode": {
                  "const": "declaredDefaultLanguage"
                }
              },
              "required": [
                "mode"
              ]
            },
            "then": {
              "required": [
                "defaultLanguage"
              ]
            },
            "else": {
              "not": {
                "required": [
                  "defaultLanguage"
                ]
              }
            },
            "unevaluatedProperties": false
          }
        }
      },
      "unevaluatedProperties": false
    },
    "publication-release-manifest.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/publication-release-manifest.schema.json",
      "title": "REF PublicationReleaseManifest",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        },
        {
          "if": {
            "properties": {
              "releaseState": {
                "const": "complete"
              }
            },
            "required": [
              "releaseState"
            ]
          },
          "then": {
            "properties": {
              "consumerEligible": {
                "const": true
              }
            }
          },
          "else": {
            "properties": {
              "consumerEligible": {
                "const": false
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "rulespecDependency": {
                "properties": {
                  "releaseAvailability": {
                    "const": "localUnpublished"
                  }
                },
                "required": [
                  "releaseAvailability"
                ]
              }
            },
            "required": [
              "rulespecDependency"
            ]
          },
          "then": {
            "properties": {
              "deploymentClass": {
                "const": "developmentOnly"
              }
            }
          }
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "version",
        "refspecVersion",
        "operationalSerializationProfile",
        "rulespecDependency",
        "claimedConformanceLevels",
        "inventoryCoveragePins",
        "rulespecReleaseGraph",
        "refOperationalRecords",
        "expressionCorpusSnapshot",
        "runReceipt",
        "releaseState",
        "deploymentClass",
        "consumerEligible",
        "publishedAt",
        "activity"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:PublicationReleaseManifest"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "version": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "refspecVersion": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "operationalSerializationProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "rulespecDependency": {
          "type": "object",
          "required": [
            "version",
            "contractRevision",
            "evidenceRevision",
            "constraintDigest",
            "conformanceCorpusDigest",
            "adoptedProfiles",
            "validator",
            "conformanceResult",
            "releaseAvailability"
          ],
          "properties": {
            "version": {
              "$ref": "common.schema.json#/$defs/nonEmptyString"
            },
            "contractRevision": {
              "type": "string",
              "pattern": "^[0-9a-f]{40}$"
            },
            "evidenceRevision": {
              "type": "string",
              "pattern": "^[0-9a-f]{40}$"
            },
            "constraintDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "conformanceCorpusDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "adoptedProfiles": {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            "validator": {
              "$ref": "common.schema.json#/$defs/componentPin"
            },
            "conformanceResult": {
              "$ref": "common.schema.json#/$defs/digestReference"
            },
            "releaseAvailability": {
              "enum": [
                "localUnpublished",
                "published"
              ]
            }
          },
          "additionalProperties": false
        },
        "claimedConformanceLevels": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/nonEmptyString"
          }
        },
        "inventoryCoveragePins": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "rulespecReleaseGraph": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "refOperationalRecords": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "expressionCorpusSnapshot": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "runReceipt": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "releaseState": {
          "enum": [
            "incomplete",
            "complete",
            "rolledBack"
          ]
        },
        "deploymentClass": {
          "enum": [
            "developmentOnly",
            "production"
          ]
        },
        "consumerEligible": {
          "type": "boolean"
        },
        "publishedAt": {
          "type": "string",
          "format": "date-time"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "predecessor": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "rollbackOf": {
          "$ref": "common.schema.json#/$defs/digestReference"
        }
      },
      "unevaluatedProperties": false
    },
    "release-graph-validation-receipt.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/release-graph-validation-receipt.schema.json",
      "title": "REF ReleaseGraphValidationReceipt",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "receiptVersion",
        "rulespecDependencyManifest",
        "rulespecGraph",
        "refRecordDigests",
        "rulespecValidator",
        "rulespecBehaviorRuntime",
        "gateImplementation",
        "verdicts",
        "authorizationEvaluations",
        "coveredRulespecIdentifiers",
        "crossReferencesDigest",
        "validatedAt",
        "activity"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:ReleaseGraphValidationReceipt"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "receiptVersion": {
          "const": "1.0"
        },
        "rulespecDependencyManifest": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "rulespecGraph": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "refRecordDigests": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "rulespecValidator": {
          "$ref": "common.schema.json#/$defs/componentPin"
        },
        "rulespecBehaviorRuntime": {
          "$ref": "common.schema.json#/$defs/componentPin"
        },
        "gateImplementation": {
          "$ref": "common.schema.json#/$defs/componentPin"
        },
        "verdicts": {
          "type": "object",
          "required": [
            "refBinding",
            "rulespecConformance",
            "rulespecBehavior",
            "crossBoundary"
          ],
          "properties": {
            "refBinding": {
              "const": "pass"
            },
            "rulespecConformance": {
              "const": "pass"
            },
            "rulespecBehavior": {
              "const": "pass"
            },
            "crossBoundary": {
              "const": "pass"
            }
          },
          "additionalProperties": false
        },
        "authorizationEvaluations": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "governanceRecord",
              "behaviorTest",
              "inputGraph",
              "behaviorContract",
              "subjectAssertion",
              "evaluationScope",
              "evaluationTime",
              "minimumUsageEligibility",
              "effectiveUsageEligibility",
              "outputDigest",
              "runtime",
              "result"
            ],
            "properties": {
              "governanceRecord": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "behaviorTest": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "inputGraph": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "behaviorContract": {
                "const": "rkaf:UsageEligibilityReducer"
              },
              "subjectAssertion": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "evaluationScope": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "evaluationTime": {
                "type": "string",
                "format": "date-time"
              },
              "minimumUsageEligibility": {
                "const": "rkaf:localOperationalUse"
              },
              "effectiveUsageEligibility": {
                "enum": [
                  "rkaf:localOperationalUse",
                  "rkaf:publicationAllowed",
                  "rkaf:officialUse"
                ]
              },
              "outputDigest": {
                "$ref": "common.schema.json#/$defs/digest"
              },
              "runtime": {
                "$ref": "common.schema.json#/$defs/componentPin"
              },
              "result": {
                "const": "pass"
              }
            },
            "additionalProperties": false
          }
        },
        "coveredRulespecIdentifiers": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "crossReferencesDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "validatedAt": {
          "type": "string",
          "format": "date-time"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        }
      },
      "unevaluatedProperties": false
    },
    "source-identifier-set.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/source-identifier-set.schema.json",
      "title": "REF SourceIdentifierSet",
      "x-ref-python-name": "SourceIdentifierSetData",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "sourceObservation",
        "sourceCapture",
        "sourcePath",
        "sourceOrdinal",
        "identifiers",
        "canonicalIdentifierSelected",
        "activity",
        "receipt"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:SourceIdentifierSet"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "sourceObservation": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "sourceCapture": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "sourcePath": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "sourceOrdinal": {
          "type": "integer",
          "minimum": 0
        },
        "identifiers": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/controlledIdentifier"
          }
        },
        "canonicalIdentifierSelected": {
          "const": false
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "receipt": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        }
      },
      "unevaluatedProperties": false
    },
    "ref-record.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/ref-record.schema.json",
      "title": "REF JSON Binding 1.0 record",
      "oneOf": [
        {
          "$ref": "capture.schema.json"
        },
        {
          "$ref": "rights-assessment.schema.json"
        },
        {
          "$ref": "run-receipt.schema.json"
        },
        {
          "$ref": "registry-import-snapshot.schema.json"
        },
        {
          "$ref": "publication-release-manifest.schema.json"
        },
        {
          "$ref": "release-graph-validation-receipt.schema.json"
        },
        {
          "$ref": "concept-proposal.schema.json"
        },
        {
          "$ref": "enrichment-profile.schema.json"
        },
        {
          "$ref": "output-profile.schema.json"
        },
        {
          "$ref": "registry-import-coverage-report.schema.json"
        },
        {
          "$ref": "indexed-vocabulary-expression.schema.json"
        },
        {
          "$ref": "registry-reconciliation-report.schema.json"
        },
        {
          "$ref": "registry-deployment-decision.schema.json"
        },
        {
          "$ref": "sealed-gold-manifest.schema.json"
        },
        {
          "$ref": "enrichment-configuration.schema.json"
        },
        {
          "$ref": "enrichment-evaluation-result.schema.json"
        },
        {
          "$ref": "enrichment-deployment-decision.schema.json"
        },
        {
          "$ref": "source-identifier-set.schema.json"
        }
      ]
    },
    "registry-deployment-decision.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/registry-deployment-decision.schema.json",
      "title": "REF RegistryDeploymentDecision",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "environment",
        "registryImportSnapshot",
        "rightsAssessment",
        "adoptedPolicyRefs",
        "referenceResourceRelease",
        "coverageReport",
        "outputProfile",
        "selectionState",
        "effectiveAt",
        "reason",
        "activity",
        "rulespecAttestationRefs",
        "localAdoptionRefs"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RegistryDeploymentDecision"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "environment": {
          "type": "object",
          "required": [
            "id",
            "classification"
          ],
          "properties": {
            "id": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "classification": {
              "enum": [
                "development",
                "staging",
                "production"
              ]
            }
          },
          "additionalProperties": false
        },
        "registryImportSnapshot": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "rightsAssessment": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "adoptedPolicyRefs": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/absoluteIri"
          }
        },
        "referenceResourceRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "coverageReport": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "reconciliationReport": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "outputProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "selectionState": {
          "enum": [
            "quarantined",
            "staged",
            "selected",
            "deselected",
            "failed"
          ]
        },
        "effectiveAt": {
          "type": "string",
          "format": "date-time"
        },
        "reason": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "rulespecAttestationRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "localAdoptionRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "authorizationValidations": {
          "description": "Deprecated, non-authoritative caller report retained only for migration. A selected deployment is authorized only by a gate-issued ReleaseGraphValidationReceipt that binds a pinned Rulespec L4 evaluation.",
          "type": "array",
          "minItems": 2,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "authorizationRef",
              "kind",
              "validationReceipt",
              "validator",
              "validatedAt",
              "effective"
            ],
            "properties": {
              "authorizationRef": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "kind": {
                "enum": [
                  "rulespecAttestation",
                  "localAdoption"
                ]
              },
              "validationReceipt": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "validator": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "validatedAt": {
                "type": "string",
                "format": "date-time"
              },
              "effective": {
                "const": true
              }
            },
            "additionalProperties": false
          }
        },
        "predecessor": {
          "$ref": "common.schema.json#/$defs/digestReference"
        }
      },
      "unevaluatedProperties": false
    },
    "registry-import-coverage-report.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/registry-import-coverage-report.schema.json",
      "title": "REF RegistryImportCoverageReport",
      "$defs": {
        "accountItem": {
          "type": "object",
          "required": [
            "id",
            "stage",
            "count",
            "policy",
            "rationale"
          ],
          "properties": {
            "id": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "stage": {
              "enum": [
                "parsing",
                "indexing"
              ]
            },
            "count": {
              "type": "integer",
              "minimum": 1
            },
            "policy": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            },
            "rationale": {
              "$ref": "common.schema.json#/$defs/nonEmptyString"
            }
          },
          "additionalProperties": false
        }
      },
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "outputProfile",
        "registryImportSnapshot",
        "referenceResourceRelease",
        "distributionArtifacts",
        "importProfile",
        "parserVersion",
        "expressionCorpusSnapshot",
        "activity",
        "receipt",
        "reportStatus",
        "features"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RegistryImportCoverageReport"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "outputProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "registryImportSnapshot": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "referenceResourceRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "distributionArtifacts": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "importProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "parserVersion": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "expressionCorpusSnapshot": {
          "description": "Exact RefSpec-owned logical expression-corpus snapshot produced by the indexed import stage.",
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "receipt": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "reportStatus": {
          "enum": [
            "pass",
            "fail"
          ]
        },
        "features": {
          "description": "Complete feature accounting. Mapping-set imports used for candidates or output require mappings, identifiers, and membership.",
          "type": "array",
          "minItems": 11,
          "maxItems": 11,
          "items": {
            "type": "object",
            "required": [
              "feature",
              "requiredForCandidateOrOutput",
              "sourceObservedCount",
              "parsedCount",
              "indexedCount",
              "excludedCount",
              "failedCount",
              "sourceObservedDigest",
              "parsedDigest",
              "indexedDigest",
              "exclusions",
              "failures"
            ],
            "properties": {
              "feature": {
                "enum": [
                  "labels",
                  "languages",
                  "notation",
                  "notes",
                  "hierarchy",
                  "associativeRelations",
                  "mappings",
                  "status",
                  "replacements",
                  "identifiers",
                  "membership"
                ]
              },
              "requiredForCandidateOrOutput": {
                "type": "boolean"
              },
              "sourceObservedCount": {
                "type": "integer",
                "minimum": 0
              },
              "parsedCount": {
                "type": "integer",
                "minimum": 0
              },
              "indexedCount": {
                "type": "integer",
                "minimum": 0
              },
              "excludedCount": {
                "type": "integer",
                "minimum": 0
              },
              "failedCount": {
                "type": "integer",
                "minimum": 0
              },
              "sourceObservedDigest": {
                "$ref": "common.schema.json#/$defs/digest"
              },
              "parsedDigest": {
                "$ref": "common.schema.json#/$defs/digest"
              },
              "indexedDigest": {
                "$ref": "common.schema.json#/$defs/digest"
              },
              "parseDifferenceExplanation": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "indexDifferenceExplanation": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "exclusions": {
                "type": "array",
                "items": {
                  "$ref": "#/$defs/accountItem"
                }
              },
              "failures": {
                "type": "array",
                "items": {
                  "$ref": "#/$defs/accountItem"
                }
              }
            },
            "additionalProperties": false
          }
        }
      },
      "unevaluatedProperties": false
    },
    "registry-import-snapshot.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/registry-import-snapshot.schema.json",
      "title": "REF RegistryImportSnapshot",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        },
        {
          "anyOf": [
            {
              "required": [
                "captures"
              ],
              "properties": {
                "captures": {
                  "minItems": 1
                }
              }
            },
            {
              "required": [
                "externalReferences"
              ],
              "properties": {
                "externalReferences": {
                  "minItems": 1
                }
              }
            }
          ]
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "inventoryCoverageComponent",
        "importProfile",
        "captures",
        "externalReferences",
        "referenceResourceRelease",
        "distributionArtifacts",
        "rightsAssessment",
        "adoptedPolicyRefs",
        "transformation",
        "exclusions",
        "failures",
        "rulespecValidationResult",
        "refValidationResult",
        "expectedRefreshCadence",
        "activity",
        "receipt"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RegistryImportSnapshot"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "inventoryCoverageComponent": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "importProfile": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "captures": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "externalReferences": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/absoluteIri"
          }
        },
        "referenceResourceRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "distributionArtifacts": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "rightsAssessment": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "adoptedPolicyRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "transformation": {
          "$ref": "common.schema.json#/$defs/componentPin"
        },
        "exclusions": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "failures": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "rulespecValidationResult": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "refValidationResult": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "expectedRefreshCadence": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "receipt": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "predecessorImportSnapshot": {
          "$ref": "common.schema.json#/$defs/digestReference"
        }
      },
      "unevaluatedProperties": false
    },
    "registry-reconciliation-report.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/registry-reconciliation-report.schema.json",
      "title": "REF RegistryReconciliationReport",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        },
        {
          "if": {
            "properties": {
              "outcome": {
                "const": "selectedInput"
              }
            },
            "required": [
              "outcome"
            ]
          },
          "then": {
            "required": [
              "selectedInputRelease"
            ],
            "properties": {
              "unresolvedItems": {
                "maxItems": 0
              },
              "synthesizedUnionAuthorized": {
                "const": false
              }
            },
            "not": {
              "required": [
                "reconciledRelease"
              ]
            }
          }
        },
        {
          "if": {
            "properties": {
              "outcome": {
                "const": "reconciledReleaseAuthorized"
              }
            },
            "required": [
              "outcome"
            ]
          },
          "then": {
            "required": [
              "reconciledRelease"
            ],
            "properties": {
              "unresolvedItems": {
                "maxItems": 0
              },
              "synthesizedUnionAuthorized": {
                "const": true
              }
            },
            "not": {
              "required": [
                "selectedInputRelease"
              ]
            }
          }
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "inputs",
        "comparedItems",
        "differences",
        "conceptMappings",
        "precedencePolicy",
        "rulespecAuthorityRefs",
        "attestationRefs",
        "localAdoptionRefs",
        "unresolvedItems",
        "synthesizedUnionAuthorized",
        "activity",
        "outcome"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RegistryReconciliationReport"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "inputs": {
          "type": "array",
          "minItems": 2,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "referenceResourceRelease",
              "distributionArtifacts",
              "registryImportSnapshot",
              "stageDigests"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "referenceResourceRelease": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              },
              "distributionArtifacts": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "$ref": "common.schema.json#/$defs/digestReference"
                }
              },
              "registryImportSnapshot": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "stageDigests": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "$ref": "common.schema.json#/$defs/digestReference"
                }
              }
            },
            "additionalProperties": false
          }
        },
        "comparedItems": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "kind",
              "left",
              "right"
            ],
            "properties": {
              "kind": {
                "enum": [
                  "field",
                  "member",
                  "relation",
                  "stageDigest"
                ]
              },
              "left": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "right": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "additionalProperties": false
          }
        },
        "differences": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "kind",
              "inputRefs",
              "description",
              "resolution"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "kind": {
                "enum": [
                  "field",
                  "member",
                  "relation",
                  "stageDigest"
                ]
              },
              "inputRefs": {
                "allOf": [
                  {
                    "$ref": "common.schema.json#/$defs/iriList"
                  },
                  {
                    "minItems": 2
                  }
                ]
              },
              "description": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              },
              "resolution": {
                "enum": [
                  "selectedInput",
                  "mapped",
                  "reconciled",
                  "unresolved"
                ]
              }
            },
            "additionalProperties": false
          }
        },
        "conceptMappings": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "precedencePolicy": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "rulespecAuthorityRefs": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "attestationRefs": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "localAdoptionRefs": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 1
            }
          ]
        },
        "authorizationValidations": {
          "description": "Deprecated, non-authoritative caller report retained only for migration. A resolved reconciliation is authorized only by a gate-issued ReleaseGraphValidationReceipt that binds a pinned Rulespec L4 evaluation.",
          "type": "array",
          "minItems": 3,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "authorizationRef",
              "kind",
              "validationReceipt",
              "validator",
              "validatedAt",
              "effective"
            ],
            "properties": {
              "authorizationRef": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "kind": {
                "enum": [
                  "rulespecAuthority",
                  "rulespecAttestation",
                  "localAdoption"
                ]
              },
              "validationReceipt": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "validator": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "validatedAt": {
                "type": "string",
                "format": "date-time"
              },
              "effective": {
                "const": true
              }
            },
            "additionalProperties": false
          }
        },
        "unresolvedItems": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "selectedInputRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "reconciledRelease": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "synthesizedUnionAuthorized": {
          "type": "boolean"
        },
        "activity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "outcome": {
          "enum": [
            "selectedInput",
            "reconciledReleaseAuthorized",
            "unresolved"
          ]
        }
      },
      "if": {
        "properties": {
          "outcome": {
            "const": "unresolved"
          }
        }
      },
      "then": {
        "required": [
          "unresolvedItems"
        ],
        "properties": {
          "unresolvedItems": {
            "minItems": 1
          },
          "synthesizedUnionAuthorized": {
            "const": false
          }
        },
        "not": {
          "anyOf": [
            {
              "required": [
                "selectedInputRelease"
              ]
            },
            {
              "required": [
                "reconciledRelease"
              ]
            }
          ]
        }
      },
      "unevaluatedProperties": false
    },
    "rights-assessment.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/rights-assessment.schema.json",
      "title": "REF RightsAssessment",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "target",
        "observedTerms",
        "supportingSourceFragments",
        "permissions",
        "purpose",
        "attribution",
        "audience",
        "effectiveAt",
        "rulespecPolicyRefs",
        "attestationRefs",
        "localAdoptionRefs"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RightsAssessment"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "target": {
          "type": "object",
          "required": [
            "kind",
            "reference"
          ],
          "properties": {
            "kind": {
              "enum": [
                "source",
                "referenceResourceRelease"
              ]
            },
            "reference": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            }
          },
          "additionalProperties": false
        },
        "observedTerms": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": [
              "sourceFragment",
              "summary"
            ],
            "properties": {
              "sourceFragment": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "summary": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "additionalProperties": false
          }
        },
        "supportingSourceFragments": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/absoluteIri"
          }
        },
        "permissions": {
          "type": "object",
          "required": [
            "acquisition",
            "storage",
            "indexing",
            "modelUse",
            "display",
            "redistribution",
            "retention"
          ],
          "properties": {
            "acquisition": {
              "$ref": "#/$defs/permission"
            },
            "storage": {
              "$ref": "#/$defs/permission"
            },
            "indexing": {
              "$ref": "#/$defs/permission"
            },
            "modelUse": {
              "$ref": "#/$defs/permission"
            },
            "display": {
              "$ref": "#/$defs/permission"
            },
            "redistribution": {
              "$ref": "#/$defs/permission"
            },
            "retention": {
              "$ref": "#/$defs/permission"
            }
          },
          "additionalProperties": false
        },
        "purpose": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "attribution": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "audience": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "effectiveAt": {
          "type": "string",
          "format": "date-time"
        },
        "priorAssessment": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "rulespecPolicyRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "attestationRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "localAdoptionRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        }
      },
      "$defs": {
        "permission": {
          "enum": [
            "permitted",
            "prohibited",
            "unclear",
            "notApplicable"
          ]
        }
      },
      "unevaluatedProperties": false
    },
    "run-receipt.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/run-receipt.schema.json",
      "title": "REF RunReceipt",
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "inputCaptures",
        "inputSnapshots",
        "rulespecReleases",
        "coverageWindow",
        "rulespecActivityRefs",
        "rulespecAgentRefs",
        "rulespecOutputRefs",
        "environmentLock",
        "outputs",
        "counts",
        "exclusions",
        "failures",
        "quarantinedItems",
        "startedAt",
        "endedAt",
        "nondeterministicStages",
        "reproducibility"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:RunReceipt"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "inputCaptures": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "inputSnapshots": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "rulespecReleases": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/versionedDigestReference"
          }
        },
        "coverageWindow": {
          "type": "object",
          "required": [
            "startedAt",
            "endedAt"
          ],
          "properties": {
            "startedAt": {
              "type": "string",
              "format": "date-time"
            },
            "endedAt": {
              "type": "string",
              "format": "date-time"
            }
          },
          "additionalProperties": false
        },
        "rulespecActivityRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "rulespecAgentRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "rulespecOutputRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "providerDetailsReference": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        },
        "environmentLock": {
          "$ref": "common.schema.json#/$defs/digestReference"
        },
        "outputs": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/digestReference"
          }
        },
        "counts": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": {
            "type": "integer",
            "minimum": 0
          }
        },
        "exclusions": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "failures": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "quarantinedItems": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "startedAt": {
          "type": "string",
          "format": "date-time"
        },
        "endedAt": {
          "type": "string",
          "format": "date-time"
        },
        "nondeterministicStages": {
          "type": "array",
          "uniqueItems": true,
          "items": {
            "$ref": "common.schema.json#/$defs/nonEmptyString"
          }
        },
        "reproducibility": {
          "enum": [
            "byteIdentical",
            "deterministicFromPinnedInputs",
            "replayableWithNondeterminism",
            "notReplayable"
          ]
        },
        "replayLimit": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        }
      },
      "unevaluatedProperties": false
    },
    "sealed-gold-manifest.schema.json": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "$id": "https://refspec.org/bindings/json/1.0/schemas/sealed-gold-manifest.schema.json",
      "title": "REF SealedGoldManifest",
      "$defs": {
        "goldTarget": {
          "oneOf": [
            {
              "type": "object",
              "required": [
                "target",
                "release",
                "grade",
                "adequate",
                "independentlyReviewed"
              ],
              "properties": {
                "target": {
                  "$ref": "common.schema.json#/$defs/absoluteIri"
                },
                "release": {
                  "$ref": "common.schema.json#/$defs/versionedDigestReference"
                },
                "grade": {
                  "enum": [
                    "exact",
                    "close",
                    "targetBroaderThanGold",
                    "targetNarrowerThanGold",
                    "related",
                    "wrong"
                  ]
                },
                "adequate": {
                  "type": "boolean"
                },
                "independentlyReviewed": {
                  "type": "boolean"
                },
                "adequacyPolicy": {
                  "$ref": "common.schema.json#/$defs/versionedDigestReference"
                }
              },
              "additionalProperties": false
            },
            {
              "type": "object",
              "required": [
                "grade",
                "adequate",
                "independentlyReviewed"
              ],
              "properties": {
                "grade": {
                  "const": "notRepresented"
                },
                "adequate": {
                  "const": false
                },
                "independentlyReviewed": {
                  "type": "boolean"
                }
              },
              "additionalProperties": false
            }
          ]
        },
        "partitionKeys": {
          "type": "object",
          "required": [
            "conceptIdentity",
            "exactMatchCluster",
            "alias",
            "sourceIdentity",
            "artifactDigest",
            "textDigest",
            "nearDuplicateCluster"
          ],
          "properties": {
            "conceptIdentity": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "exactMatchCluster": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "alias": {
              "description": "Normalized indexed-text identities for every preferred, alternate, hidden, or acceptable open-label form associated with the item.",
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/nonEmptyString"
              }
            },
            "sourceIdentity": {
              "allOf": [
                {
                  "$ref": "common.schema.json#/$defs/stringList"
                },
                {
                  "minItems": 1
                }
              ]
            },
            "artifactDigest": {
              "allOf": [
                {
                  "$ref": "common.schema.json#/$defs/stringList"
                },
                {
                  "minItems": 1
                }
              ]
            },
            "textDigest": {
              "allOf": [
                {
                  "$ref": "common.schema.json#/$defs/stringList"
                },
                {
                  "minItems": 1
                }
              ]
            },
            "nearDuplicateCluster": {
              "allOf": [
                {
                  "$ref": "common.schema.json#/$defs/stringList"
                },
                {
                  "minItems": 1
                }
              ]
            }
          },
          "additionalProperties": false
        },
        "partitionEvidence": {
          "type": "object",
          "required": [
            "sourceTextDigest",
            "vocabularyExpressionCorpusDigest",
            "exactMatchGraphDigest",
            "nearDuplicateAnalysisDigest",
            "receipt"
          ],
          "properties": {
            "sourceTextDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "vocabularyExpressionCorpusDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "exactMatchGraphDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "nearDuplicateAnalysisDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "receipt": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            }
          },
          "additionalProperties": false
        }
      },
      "allOf": [
        {
          "$ref": "common.schema.json#/$defs/commonRecordProperties"
        }
      ],
      "required": [
        "canonicalPayloadDigest",
        "evaluationGeneration",
        "purpose",
        "selectionProtocol",
        "sourceDigest",
        "corpusDigest",
        "selectionDigest",
        "draftingControl",
        "partitions",
        "items",
        "vocabularyUniverse",
        "expectations",
        "reviewers",
        "independentJudgmentRefs",
        "disagreementRefs",
        "adjudicationRefs",
        "exclusions",
        "partitionReport",
        "sealingTime",
        "sealingActivity"
      ],
      "properties": {
        "type": {
          "const": "urn:ref:type:SealedGoldManifest"
        },
        "canonicalPayloadDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "evaluationGeneration": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "purpose": {
          "$ref": "common.schema.json#/$defs/nonEmptyString"
        },
        "selectionProtocol": {
          "$ref": "common.schema.json#/$defs/versionedDigestReference"
        },
        "sourceDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "corpusDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "selectionDigest": {
          "$ref": "common.schema.json#/$defs/digest"
        },
        "draftingControl": {
          "type": "object",
          "required": [
            "protocol",
            "blindToEvaluatedOutput",
            "prohibitedSeedSources"
          ],
          "properties": {
            "protocol": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            },
            "blindToEvaluatedOutput": {
              "const": true
            },
            "prohibitedSeedSources": {
              "type": "array",
              "minItems": 4,
              "maxItems": 4,
              "uniqueItems": true,
              "items": {
                "enum": [
                  "modelOutput",
                  "candidateRank",
                  "priorSystemDecision",
                  "developerPreference"
                ]
              }
            }
          },
          "additionalProperties": false
        },
        "partitions": {
          "type": "object",
          "required": [
            "development",
            "holdout"
          ],
          "properties": {
            "development": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              }
            },
            "holdout": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              }
            }
          },
          "additionalProperties": false
        },
        "items": {
          "type": "array",
          "minItems": 2,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "split",
              "sourceResource",
              "renditionArtifact",
              "sourceFragment",
              "sourceFamily",
              "subtype",
              "selectionStrata",
              "linkedGroupIds",
              "partitionKeys",
              "partitionEvidence"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "split": {
                "enum": [
                  "development",
                  "holdout"
                ]
              },
              "sourceResource": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "renditionArtifact": {
                "$ref": "common.schema.json#/$defs/digestReference"
              },
              "sourceFragment": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "sourceFamily": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "subtype": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "selectionStrata": {
                "allOf": [
                  {
                    "$ref": "common.schema.json#/$defs/iriList"
                  },
                  {
                    "minItems": 1
                  }
                ]
              },
              "linkedGroupIds": {
                "$ref": "common.schema.json#/$defs/iriList"
              },
              "partitionKeys": {
                "$ref": "#/$defs/partitionKeys"
              },
              "partitionEvidence": {
                "$ref": "#/$defs/partitionEvidence"
              }
            },
            "additionalProperties": false
          }
        },
        "vocabularyUniverse": {
          "type": "object",
          "required": [
            "referenceResourceReleases",
            "registryImportSnapshots",
            "mappingReleases",
            "mappingSnapshots",
            "indexedExpressionCorpusDigests",
            "enrichmentProfile",
            "outputProfile",
            "normalizationPolicy",
            "candidateTargetUniverseDigest"
          ],
          "properties": {
            "referenceResourceReleases": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "registryImportSnapshots": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digestReference"
              }
            },
            "mappingReleases": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/versionedDigestReference"
              }
            },
            "mappingSnapshots": {
              "type": "array",
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digestReference"
              }
            },
            "indexedExpressionCorpusDigests": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digest"
              }
            },
            "enrichmentProfile": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            },
            "outputProfile": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            },
            "normalizationPolicy": {
              "$ref": "common.schema.json#/$defs/versionedDigestReference"
            },
            "candidateTargetUniverseDigest": {
              "$ref": "common.schema.json#/$defs/digest"
            }
          },
          "additionalProperties": false
        },
        "expectations": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "type": "object",
            "required": [
              "id",
              "item",
              "facet",
              "assignmentRole",
              "expectationMode",
              "minimumCardinality",
              "maximumCardinality",
              "validZeroResult",
              "registeredTargets",
              "acceptableOpenLabels",
              "conceptProposalAllowed",
              "abstentionAllowed",
              "forbiddenResults",
              "wrongFacetOutcomes",
              "evidenceRefs",
              "reviewerJudgments",
              "disagreement",
              "excludeFromReachableCandidateRecall",
              "includeInTargetAvailability",
              "includeInOpenSetMeasures"
            ],
            "properties": {
              "id": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "item": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "facet": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "assignmentRole": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "expectationMode": {
                "enum": [
                  "completeSet",
                  "cardinalityRange"
                ]
              },
              "minimumCardinality": {
                "type": "integer",
                "minimum": 0
              },
              "maximumCardinality": {
                "type": "integer",
                "minimum": 0
              },
              "validZeroResult": {
                "type": "boolean"
              },
              "registeredTargets": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                  "$ref": "#/$defs/goldTarget"
                }
              },
              "acceptableOpenLabels": {
                "type": "array",
                "uniqueItems": true,
                "items": {
                  "type": "object",
                  "required": [
                    "value",
                    "language"
                  ],
                  "properties": {
                    "value": {
                      "$ref": "common.schema.json#/$defs/nonEmptyString"
                    },
                    "language": {
                      "$ref": "common.schema.json#/$defs/bcp47Language"
                    }
                  },
                  "additionalProperties": false
                }
              },
              "conceptProposalAllowed": {
                "type": "boolean"
              },
              "abstentionAllowed": {
                "type": "boolean"
              },
              "forbiddenResults": {
                "$ref": "common.schema.json#/$defs/iriList"
              },
              "wrongFacetOutcomes": {
                "$ref": "common.schema.json#/$defs/iriList"
              },
              "evidenceRefs": {
                "allOf": [
                  {
                    "$ref": "common.schema.json#/$defs/iriList"
                  },
                  {
                    "minItems": 1
                  }
                ]
              },
              "reviewerJudgments": {
                "type": "array",
                "minItems": 2,
                "uniqueItems": true,
                "items": {
                  "type": "object",
                  "required": [
                    "reviewer",
                    "judgment"
                  ],
                  "properties": {
                    "reviewer": {
                      "$ref": "common.schema.json#/$defs/absoluteIri"
                    },
                    "judgment": {
                      "$ref": "common.schema.json#/$defs/absoluteIri"
                    }
                  },
                  "additionalProperties": false
                }
              },
              "disagreement": {
                "type": "boolean"
              },
              "adjudication": {
                "type": "object",
                "required": [
                  "adjudicator",
                  "judgment"
                ],
                "properties": {
                  "adjudicator": {
                    "$ref": "common.schema.json#/$defs/absoluteIri"
                  },
                  "judgment": {
                    "$ref": "common.schema.json#/$defs/absoluteIri"
                  }
                },
                "additionalProperties": false
              },
              "exclusion": {
                "$ref": "common.schema.json#/$defs/absoluteIri"
              },
              "excludeFromReachableCandidateRecall": {
                "type": "boolean"
              },
              "includeInTargetAvailability": {
                "type": "boolean"
              },
              "includeInOpenSetMeasures": {
                "type": "boolean"
              }
            },
            "additionalProperties": false
          }
        },
        "reviewers": {
          "allOf": [
            {
              "$ref": "common.schema.json#/$defs/iriList"
            },
            {
              "minItems": 2
            }
          ]
        },
        "independentJudgmentRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "disagreementRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "adjudicationRefs": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "exclusions": {
          "$ref": "common.schema.json#/$defs/iriList"
        },
        "partitionReport": {
          "type": "object",
          "required": [
            "id",
            "digest",
            "inputDigests",
            "dimensions"
          ],
          "properties": {
            "id": {
              "$ref": "common.schema.json#/$defs/absoluteIri"
            },
            "digest": {
              "$ref": "common.schema.json#/$defs/digest"
            },
            "inputDigests": {
              "type": "array",
              "minItems": 1,
              "uniqueItems": true,
              "items": {
                "$ref": "common.schema.json#/$defs/digest"
              }
            },
            "dimensions": {
              "type": "array",
              "minItems": 7,
              "maxItems": 7,
              "items": {
                "type": "object",
                "required": [
                  "dimension",
                  "computationPolicy",
                  "itemKeys"
                ],
                "properties": {
                  "dimension": {
                    "enum": [
                      "conceptIdentity",
                      "exactMatchCluster",
                      "alias",
                      "sourceIdentity",
                      "artifactDigest",
                      "textDigest",
                      "nearDuplicateCluster"
                    ]
                  },
                  "computationPolicy": {
                    "$ref": "common.schema.json#/$defs/versionedDigestReference"
                  },
                  "itemKeys": {
                    "type": "array",
                    "minItems": 2,
                    "uniqueItems": true,
                    "items": {
                      "type": "object",
                      "required": [
                        "item",
                        "values"
                      ],
                      "properties": {
                        "item": {
                          "$ref": "common.schema.json#/$defs/absoluteIri"
                        },
                        "values": {
                          "type": "array",
                          "uniqueItems": true,
                          "items": {
                            "$ref": "common.schema.json#/$defs/nonEmptyString"
                          }
                        }
                      },
                      "additionalProperties": false
                    }
                  }
                },
                "additionalProperties": false
              }
            }
          },
          "additionalProperties": false
        },
        "sealingTime": {
          "type": "string",
          "format": "date-time"
        },
        "sealingActivity": {
          "$ref": "common.schema.json#/$defs/absoluteIri"
        }
      },
      "unevaluatedProperties": false
    }
  }
}
