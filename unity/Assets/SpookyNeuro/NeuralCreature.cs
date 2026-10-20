using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpookyNeuro
{
    [Serializable]
    public sealed class CreatureData
    {
        public int schema;
        public float[] vertices, normals, colors, joints, weights, morph, morphNormals;
        public int[] triangles, parents, boneIndices;
        public string[] boneNames;
    }

    // Standard skinned mesh: no Python, diffusion process, or custom engine build at runtime.
    public sealed class NeuralCreature : MonoBehaviour
    {
        public TextAsset source;
        public Material material;
        public bool walking = true;
        public bool mutate = true;
        [Range(0, 1)] public float mutationAmount = 1;
        public float walkSpeed = 1;
        public SkinnedMeshRenderer Surface { get; private set; }
        public Transform[] Bones { get; private set; }
        private CreatureData data;
        private Vector3 pelvisRest;
        private Mesh ownedMesh;
        private GameObject generatedRoot;

        static Vector3 Vector(float[] values, int i) => new Vector3(values[i*3], values[i*3+1], -values[i*3+2]);

        public void Build()
        {
            if (Surface != null) return;
            if (source == null) throw new InvalidOperationException("Assign creature.spooky.json to Source.");
            data = JsonUtility.FromJson<CreatureData>(source.text);
            if (data == null || data.schema != 1 || data.vertices == null || data.vertices.Length % 3 != 0)
                throw new InvalidOperationException("Invalid SpookyNeuro mesh payload.");
            int count = data.vertices.Length / 3;
            if (data.normals.Length != count*3 || data.colors.Length != count*4 || data.weights.Length != count*4 ||
                data.boneIndices.Length != count*4 || data.morph.Length != count*3 || data.morphNormals.Length != count*3 ||
                data.parents.Length != data.boneNames.Length || data.joints.Length != data.parents.Length*3)
                throw new InvalidOperationException("Mesh buffer sizes do not match.");
            generatedRoot = new GameObject("Generated surface & rig");
            generatedRoot.transform.SetParent(transform, false);
            Bones = new Transform[data.boneNames.Length];
            Matrix4x4[] bindPoses = new Matrix4x4[Bones.Length];
            for (int i = 0; i < Bones.Length; i++)
            {
                int parent = data.parents[i];
                if (parent >= i || parent < -1) throw new InvalidOperationException("Rig must be parent-first.");
                Bones[i] = new GameObject(data.boneNames[i]).transform;
                Bones[i].SetParent(parent >= 0 ? Bones[parent] : generatedRoot.transform, false);
                Bones[i].localPosition = Vector(data.joints, i) - (parent >= 0 ? Vector(data.joints, parent) : Vector3.zero);
                bindPoses[i] = Bones[i].worldToLocalMatrix * generatedRoot.transform.localToWorldMatrix;
            }
            pelvisRest = Bones[0].localPosition;
            Vector3[] vertices = new Vector3[count], normals = new Vector3[count], delta = new Vector3[count], deltaNormals = new Vector3[count];
            Color[] colors = new Color[count];
            BoneWeight[] weights = new BoneWeight[count];
            for (int i = 0; i < count; i++)
            {
                vertices[i] = Vector(data.vertices, i); normals[i] = Vector(data.normals, i);
                delta[i] = Vector(data.morph, i); deltaNormals[i] = Vector(data.morphNormals, i);
                colors[i] = new Color(data.colors[i*4], data.colors[i*4+1], data.colors[i*4+2], data.colors[i*4+3]);
                weights[i] = new BoneWeight {
                    boneIndex0=data.boneIndices[i*4], boneIndex1=data.boneIndices[i*4+1],
                    boneIndex2=data.boneIndices[i*4+2], boneIndex3=data.boneIndices[i*4+3],
                    weight0=data.weights[i*4], weight1=data.weights[i*4+1], weight2=data.weights[i*4+2], weight3=data.weights[i*4+3] };
            }
            int[] triangles = (int[])data.triangles.Clone();
            for (int i = 0; i < triangles.Length; i += 3)
            {
                int swap = triangles[i+1]; triangles[i+1] = triangles[i+2]; triangles[i+2] = swap;
            }
            ownedMesh = new Mesh { name="NeuralCreature", indexFormat=IndexFormat.UInt32 };
            ownedMesh.vertices=vertices; ownedMesh.normals=normals; ownedMesh.colors=colors;
            ownedMesh.triangles=triangles; ownedMesh.boneWeights=weights; ownedMesh.bindposes=bindPoses;
            ownedMesh.AddBlendShapeFrame("DensityShift", 100, delta, deltaNormals, null);
            ownedMesh.RecalculateBounds();
            Surface = generatedRoot.AddComponent<SkinnedMeshRenderer>();
            Surface.sharedMesh=ownedMesh; Surface.bones=Bones; Surface.rootBone=Bones[0];
            Surface.sharedMaterial=material;
            // Enclose all animated poses, including arm swing, not just rest-pose bounds.
            Surface.localBounds=new Bounds(new Vector3(0,1.5f,0),new Vector3(4,4,3));
            Surface.quality=SkinQuality.Bone4;
        }

        void Start() { Build(); }

        void Update()
        {
            if (Bones == null) return;
            float phase=Time.time*walkSpeed*Mathf.PI*2/2.4f;
            for (int i=0; i<Bones.Length; i++)
            {
                string name=data.boneNames[i];
                float angle=0; Vector3 axis=Vector3.right;
                float stride=Mathf.Sin(phase+(name.EndsWith("L",StringComparison.Ordinal)?Mathf.PI:0));
                if (walking)
                {
                    if (name=="Chest") angle=.12f+.045f*Mathf.Sin(2*phase);
                    else if (name=="Head") { axis=Vector3.forward; angle=.09f+.07f*Mathf.Sin(phase)+.16f*Mathf.Pow(Mathf.Max(0,Mathf.Sin(2*phase)),20); }
                    else if (name.StartsWith("Hip",StringComparison.Ordinal)) angle=.34f*stride;
                    else if (name.StartsWith("Knee",StringComparison.Ordinal)) angle=-.06f-.45f*Mathf.Max(0,-stride);
                    else if (name.StartsWith("Ankle",StringComparison.Ordinal)) angle=.09f*stride;
                    else if (name.StartsWith("Shoulder",StringComparison.Ordinal)) angle=-.22f*stride;
                    else if (name.StartsWith("Elbow",StringComparison.Ordinal)) angle=-.10f+.09f*stride;
                    if (name.EndsWith("L",StringComparison.Ordinal)) angle*=.72f;
                }
                // Mirror a right-handed glTF rotation across Z: negate rotations around X and Y.
                float handedness=axis.z==0?-1:1;
                Bones[i].localRotation=Quaternion.AngleAxis(angle*Mathf.Rad2Deg*handedness,axis);
            }
            Bones[0].localPosition=pelvisRest+Vector3.up*(walking?.018f*Mathf.Sin(2*phase):0);
            Surface.SetBlendShapeWeight(0,mutate?mutationAmount*(.5f+.5f*Mathf.Sin(Time.time*1.6f))*100:0);
        }

        void OnDestroy()
        {
            if (ownedMesh != null) Destroy(ownedMesh);
        }
    }
}
