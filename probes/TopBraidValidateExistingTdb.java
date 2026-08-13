import java.nio.file.Files;
import java.nio.file.Path;

import org.apache.jena.query.Dataset;
import org.apache.jena.query.ReadWrite;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.rdf.model.Property;
import org.apache.jena.rdf.model.Resource;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.tdb2.TDB2Factory;
import org.topbraid.shacl.validation.ValidationUtil;

/** TopBraid SHACL runner over an existing named graph in a Jena TDB2 database. */
public final class TopBraidValidateExistingTdb {
    private static final String SH = "http://www.w3.org/ns/shacl#";

    private TopBraidValidateExistingTdb() {}

    public static void main(String[] args) {
        if (args.length != 4) {
            System.err.println(
                    "usage: TopBraidValidateExistingTdb "
                            + "TDB_DIRECTORY SHAPES INOCULATED_ONTOLOGY GRAPH_IRI");
            System.exit(2);
        }
        Path databasePath = Path.of(args[0]);
        if (!Files.isDirectory(databasePath)) {
            throw new IllegalArgumentException("TDB directory does not exist: " + databasePath);
        }

        long started = System.nanoTime();
        Model shapes = ModelFactory.createDefaultModel();
        RDFDataMgr.read(shapes, Path.of(args[1]).toUri().toString());
        Model ontology = ModelFactory.createDefaultModel();
        RDFDataMgr.read(ontology, Path.of(args[2]).toUri().toString());
        Dataset dataset = TDB2Factory.connectDataset(databasePath.toString());
        long opened = System.nanoTime();

        long dataTriples;
        boolean conforms;
        long results;
        dataset.begin(ReadWrite.READ);
        try {
            Model data = dataset.getNamedModel(args[3]);
            dataTriples = data.size();
            Model validationView = ModelFactory.createUnion(data, ontology);
            Resource report = ValidationUtil.validateModel(validationView, shapes, false);
            Property conformsProperty = report.getModel().createProperty(SH + "conforms");
            Property resultProperty = report.getModel().createProperty(SH + "result");
            conforms = report.getRequiredProperty(conformsProperty).getBoolean();
            results = report.listProperties(resultProperty).toList().size();
        } finally {
            dataset.end();
            dataset.close();
        }
        long validated = System.nanoTime();

        System.out.printf(
                "engine=topbraid-shacl store=existing-tdb2 data_triples=%d "
                        + "ontology_triples=%d shape_triples=%d open_seconds=%.3f "
                        + "validate_seconds=%.3f total_seconds=%.3f "
                        + "conforms=%s results=%d%n",
                dataTriples,
                ontology.size(),
                shapes.size(),
                seconds(opened - started),
                seconds(validated - opened),
                seconds(validated - started),
                conforms,
                results);
    }

    private static double seconds(long nanoseconds) {
        return nanoseconds / 1_000_000_000.0;
    }
}
