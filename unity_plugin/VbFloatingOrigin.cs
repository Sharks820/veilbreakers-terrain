using System;
using UnityEngine;
using UnityEngine.Events;

namespace VeilBreakers.TerrainImport
{
    /// <summary>
    /// Runtime floating-origin controller for imported VeilBreakers terrain worlds.
    /// Shift terrain roots back toward zero before large-world precision loss
    /// causes vegetation, water, and terrain seams to jitter.
    /// </summary>
    public sealed class VbFloatingOrigin : MonoBehaviour
    {
        [Serializable]
        public sealed class OriginMovedEvent : UnityEvent<Vector3, Vector3>
        {
        }

        [Tooltip("Player or camera transform used as the precision anchor.")]
        public Transform ReferenceTransform;

        [Tooltip("Scene roots shifted when the reference moves too far from origin.")]
        public Transform[] ShiftRoots = Array.Empty<Transform>();

        [Tooltip("Maximum horizontal distance from local origin before recentering.")]
        public float MaximumDistance = 2048.0f;

        [Tooltip("Keep world Y untouched. Terrain worlds usually only need X/Z recentering.")]
        public bool LockY = true;

        [Tooltip("Particle systems need particle positions shifted explicitly.")]
        public bool ShiftParticles = true;

        public Vector3 AccumulatedOffset { get; private set; }

        public OriginMovedEvent OnOriginMoved = new OriginMovedEvent();

        private void LateUpdate()
        {
            var reference = ResolveReference();
            if (reference == null)
            {
                return;
            }

            var offset = reference.position;
            if (LockY)
            {
                offset.y = 0.0f;
            }

            if (offset.sqrMagnitude < MaximumDistance * MaximumDistance)
            {
                return;
            }

            ShiftWorld(offset);
        }

        public void ShiftWorld(Vector3 offset)
        {
            if (offset == Vector3.zero)
            {
                return;
            }

            var previous = AccumulatedOffset;
            AccumulatedOffset += offset;

            foreach (var root in ShiftRoots)
            {
                if (root == null)
                {
                    continue;
                }

                root.position -= offset;
            }

            if (ShiftParticles)
            {
                ShiftParticleSystems(offset);
            }

            OnOriginMoved.Invoke(AccumulatedOffset, previous);
        }

        private Transform ResolveReference()
        {
            if (ReferenceTransform != null)
            {
                return ReferenceTransform;
            }

            var mainCamera = Camera.main;
            return mainCamera != null ? mainCamera.transform : null;
        }

        private static void ShiftParticleSystems(Vector3 offset)
        {
            var particleSystems = FindObjectsOfType<ParticleSystem>();
            foreach (var system in particleSystems)
            {
                if (system == null || !system.main.simulationSpace.Equals(ParticleSystemSimulationSpace.World))
                {
                    continue;
                }

                var particles = new ParticleSystem.Particle[system.particleCount];
                var count = system.GetParticles(particles);
                for (var index = 0; index < count; index++)
                {
                    particles[index].position -= offset;
                }
                system.SetParticles(particles, count);
            }
        }
    }
}
